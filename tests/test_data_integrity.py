from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from eye_care.data.json_wal_repo import JsonWalRepo
from eye_care.data.repository import DateRange, DomainDelta, EventRecord, MinuteUsageRecord, UsageDelta
from eye_care.data.transfer import export_all, import_all


class DataIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.base = datetime.now().astimezone().replace(hour=12, minute=10, second=0, microsecond=0).astimezone(timezone.utc)
        self.day = self.base.astimezone().date().isoformat()

    def tearDown(self):
        self.tmp.cleanup()

    def repo(self, name="source"):
        return JsonWalRepo(self.root / name)

    def add(self, repo, seconds, offset=0):
        ts = self.base + timedelta(minutes=offset)
        repo.add_usage(UsageDelta("editor", seconds, ts))
        repo.add_domain_usage(DomainDelta("example.test", seconds, ts))

    def assert_totals(self, repo, seconds):
        self.assertEqual(repo.get_daily_usage(self.day), {"editor": seconds})
        self.assertEqual(repo.get_daily_domain_usage(self.day), {"example.test": seconds})
        self.assertEqual(sum(repo.get_hourly_usage(self.day).values()), seconds)
        self.assertEqual(sum(sum(v.values()) for v in repo.get_hourly_breakdown(self.day).values()), seconds)
        self.assertEqual(sum(sum(v.values()) for v in repo.get_hourly_domain_breakdown(self.day).values()), seconds)

    def test_same_minute_restarts_preserve_app_and_domain_time(self):
        for seconds in (10, 12, 3):
            repo = self.repo()
            self.add(repo, seconds)
            repo.close()
        repo = self.repo()
        self.assert_totals(repo, 25)
        repo.close()

    def test_restart_before_checkpoint_uses_cumulative_bucket_once(self):
        repo = self.repo()
        self.add(repo, 10)
        repo.close()
        repo = self.repo()
        self.add(repo, 12)
        self.add(repo, 3, offset=1)
        self.assert_totals(repo, 25)
        repo.reload_days([self.day])
        self.assert_totals(repo, 25)
        repo.merge()
        self.assert_totals(repo, 25)
        repo.close()

    def test_live_export_includes_ram_and_does_not_split_active_minute(self):
        repo = self.repo()
        self.add(repo, 10, offset=-1)
        self.add(repo, 5)
        repo.add_event(EventRecord(self.base, self.day, "rest_complete", {}))
        archive = self.root / "backup.zip"
        result = export_all(repo.data_dir, archive, repo=repo)
        self.assertEqual(result["total_domain_minutes"], 2)
        with zipfile.ZipFile(archive) as bundle:
            minutes = [json.loads(line) for line in bundle.read(f"minute_usage/minute-{self.day}.jsonl").splitlines()]
            self.assertEqual(sum(sum(row["apps"].values()) for row in minutes), 15)
            self.assertEqual(len(bundle.read(f"events/events-{self.day}.jsonl").splitlines()), 1)
        self.add(repo, 7)
        repo.close()
        repo = self.repo()
        self.assert_totals(repo, 22)
        repo.close()

    def test_offline_export_includes_unmerged_wal(self):
        repo = self.repo()
        self.add(repo, 10, offset=-1)
        self.add(repo, 5)
        archive = self.root / "backup.zip"
        result = export_all(repo.data_dir, archive)
        self.assertEqual(result["total_minutes"], 1)
        self.assertEqual(result["total_domain_minutes"], 1)
        repo.close()

    def test_events_only_and_domains_only_days_round_trip(self):
        source = self.repo()
        event_ts = self.base - timedelta(days=2)
        event_day = event_ts.astimezone().date().isoformat()
        source.add_event(EventRecord(event_ts, event_day, "rest_complete", {}))
        source.add_domain_usage(DomainDelta("example.test", 17, self.base))
        archive = self.root / "backup.zip"
        result = export_all(source.data_dir, archive, repo=source)
        self.assertEqual(result["meta"]["days"], sorted([event_day, self.day]))
        target = self.repo("target")
        import_all(target.data_dir, archive, target)
        self.assertEqual(len(target.get_events(event_day)), 1)
        self.assertEqual(target.get_daily_domain_usage(self.day), {"example.test": 17})
        target.close()
        source.close()

    def test_overlapping_backups_merge_once_and_preserve_active_data(self):
        source = self.repo()
        self.add(source, 10)
        archive = self.root / "backup.zip"
        export_all(source.data_dir, archive, repo=source)
        target = self.repo("target")
        self.add(target, 15)
        import_all(target.data_dir, archive, target)
        self.assert_totals(target, 15)
        import_all(target.data_dir, archive, target)
        self.assert_totals(target, 15)
        self.add(source, 10)
        export_all(source.data_dir, archive, repo=source)
        import_all(target.data_dir, archive, target)
        self.assert_totals(target, 20)
        self.add(target, 2)
        target.close()
        target = self.repo("target")
        self.assert_totals(target, 22)
        target.close()
        source.close()

    def test_overwrite_import_replaces_live_minute_without_resurrecting_it(self):
        source = self.repo()
        self.add(source, 10)
        archive = self.root / "backup.zip"
        export_all(source.data_dir, archive, repo=source)
        target = self.repo("target")
        self.add(target, 25)
        import_all(target.data_dir, archive, target, "overwrite_conflicts")
        self.assert_totals(target, 10)
        self.add(target, 2)
        target.close()
        target = self.repo("target")
        self.assert_totals(target, 12)
        target.close()
        source.close()

    def test_skip_import_detects_conflict_with_unmerged_local_data(self):
        source = self.repo()
        self.add(source, 10)
        archive = self.root / "backup.zip"
        export_all(source.data_dir, archive, repo=source)
        target = self.repo("target")
        self.add(target, 25)
        result = import_all(target.data_dir, archive, target, "skip_conflicts")
        self.assertEqual(result["skipped_days"], [self.day])
        self.assert_totals(target, 25)
        target.close()
        source.close()

    def test_read_recovers_valid_lines_after_corrupt_or_non_object_row(self):
        repo = self.repo()
        row = {"_schema": "minute@1", "minute_start_utc": self.base.isoformat(), "local_date": self.day, "apps": {"editor": 9}}
        path = repo.data_dir / "minute_usage" / f"minute-{self.day}.jsonl"
        path.write_text("broken\n[]\n" + json.dumps(row) + "\n", encoding="utf-8-sig")
        repo.reload_days([self.day])
        self.assertEqual(repo.get_daily_usage(self.day), {"editor": 9})
        repo.close()

    def test_failed_export_keeps_previous_archive(self):
        repo = self.repo()
        self.add(repo, 3)
        archive = self.root / "backup.zip"
        archive.write_bytes(b"previous backup")
        with patch("eye_care.data.transfer.zipfile.ZipFile.writestr", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                export_all(repo.data_dir, archive, repo=repo)
        self.assertEqual(archive.read_bytes(), b"previous backup")
        self.assertEqual(list(self.root.glob("backup.zip.*.tmp")), [])
        repo.close()

    def test_excluded_app_disappears_from_mixed_rows_and_live_minute(self):
        repo = self.repo()
        self.add(repo, 10, offset=-1)
        repo.add_usage(UsageDelta("other", 5, self.base - timedelta(minutes=1)))
        self.add(repo, 3)
        repo.merge()
        repo.delete_app_data("editor")
        self.assertEqual(repo.get_daily_usage(self.day), {"other": 5})
        self.assertEqual(repo.get_hourly_breakdown(self.day), {self.base.astimezone().hour: {"other": 5}})
        repo.close()
        repo = self.repo()
        self.assertEqual(repo.get_daily_usage(self.day), {"other": 5})
        self.assertEqual(repo.get_timeline_segments("editor", DateRange(self.day, self.day)), [])
        repo.close()

    def test_excluded_app_cannot_return_from_failed_write_buffer(self):
        repo = self.repo()
        with patch.object(repo, "_append_lines", return_value=(0, 0)):
            self.add(repo, 10, offset=-1)
            self.add(repo, 3)
        repo.delete_app_data("editor")
        repo.close()
        repo = self.repo()
        self.assertEqual(repo.get_daily_usage(self.day), {})
        repo.close()

    def test_legacy_backup_overwrite_preserves_unrepresented_site_data(self):
        repo = self.repo()
        self.add(repo, 25)
        archive = self.root / "legacy.zip"
        row = {"_schema": "minute@1", "minute_start_utc": self.base.isoformat(), "local_date": self.day, "apps": {"editor": 10}}
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("_meta.json", json.dumps({"schema": "eye_care_export@4", "export_id": "legacy-test", "days": [self.day]}))
            bundle.writestr(f"minute_usage/minute-{self.day}.jsonl", json.dumps(row) + "\n")
        import_all(repo.data_dir, archive, repo, "overwrite_conflicts")
        self.assertEqual(repo.get_daily_usage(self.day), {"editor": 10})
        self.assertEqual(repo.get_daily_domain_usage(self.day), {"example.test": 25})
        repo.close()

    def test_replayed_minute_snapshots_do_not_inflate_cache(self):
        repo = self.repo()
        for seconds in (10, 15, 10):
            repo.add_minute(MinuteUsageRecord(self.base, self.day, {"editor": seconds}))
        self.assertEqual(repo.get_daily_usage(self.day), {"editor": 15})
        repo.close()
        repo = self.repo()
        self.assertEqual(repo.get_daily_usage(self.day), {"editor": 15})
        repo.close()


if __name__ == "__main__":
    unittest.main()

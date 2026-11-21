from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from eye_care.config.models import AppConfig
from eye_care.config.store import load_config
from eye_care.data.json_wal_repo import JsonWalRepo
from eye_care.data.repository import DomainDelta, EventRecord, UsageDelta
from eye_care.services.ai_export import build_ai_export
from eye_care.services.notion_client import NotionClient, NotionError, rich_text, daily_properties
from eye_care.services.device_identity import installation_id, sync_directory_lock
from eye_care.services.notion_credentials import NotionCredentials
from eye_care.services.notion_sync import NotionSyncService

PARENT = "12345678-1234-4234-8234-123456789abc"


class MemoryCredentials:
    def __init__(self): self.token = "test-only-fake-token"
    def exists(self): return bool(self.token)
    def load(self): return self.token
    def save(self, token): self.token = token
    def clear(self): self.token = ""


class FakeNotion:
    def __init__(self):
        self.pages = {}
        self.created = self.updated = 0
        self.lose_create_response = False

    def prepare_record(self, report):
        return report

    def refresh_dashboard(self, source, days, changed_totals):
        pass

    def resolve_source(self, parent):
        return parent, parent

    def get_record(self, source, target, key, device, day):
        value = self.pages.get(target)
        return {"id": target, "properties": daily_properties(value["report"], value["digest"])} if value else None

    def find_day(self, source, key, device, day):
        rows = [{"id": k, "properties": daily_properties(v["report"], v["digest"])} for k, v in self.pages.items()
                if v["parent"] == source and v["report"]["sync_key"] == key]
        if len(rows) > 1:
            raise NotionError("duplicate row")
        return rows[0] if rows else None

    def create_record(self, parent, report, digest):
        key = str(uuid.uuid4())
        self.pages[key] = {"parent": parent, "digest": digest, "report": copy.deepcopy(report)}
        self.created += 1
        if self.lose_create_response:
            self.lose_create_response = False
            raise NotionError("simulated response loss")
        return key

    def update_record(self, target, report, digest):
        self.updated += 1
        self.pages[target]["report"] = copy.deepcopy(report)
        self.pages[target]["digest"] = digest


class NotionSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = JsonWalRepo(self.root)
        self.cfg = AppConfig(notion_parent_page=PARENT, notion_sync_days=1)
        self.c = SimpleNamespace(data_dir=self.root, cfg_path=self.root / "config.json", cfg=self.cfg, repo=self.repo)
        self.now = datetime.now().astimezone().replace(hour=12, minute=10, second=0, microsecond=0)
        self.day = self.now.date().isoformat()
        self.remote, self.creds = FakeNotion(), MemoryCredentials()
        self.service = self.new_service()

    def new_service(self, **kwargs):
        return NotionSyncService(self.c, credentials=self.creds, client_factory=lambda token: self.remote, **kwargs)

    def tearDown(self):
        self.repo.close()
        self.tmp.cleanup()

    def usage(self, seconds):
        self.repo.add_usage(UsageDelta("editor", seconds, self.now))

    def test_report_filters_blacklist_and_omits_sites_by_default(self):
        self.usage(10)
        self.repo.add_usage(UsageDelta("private", 20, self.now))
        self.repo.add_domain_usage(DomainDelta("example.test", 7, self.now))
        self.cfg.blacklist_apps = ["private"]
        self.cfg.record_browser_enabled = True
        report = build_ai_export(self.c, 1, False, now=self.now)["days"][0]
        self.assertEqual(report["total_usage_seconds"], 10)
        self.assertEqual(report["sites"], [])
        self.assertNotIn("private", json.dumps(report))
        self.assertNotIn("test-only-fake-token", json.dumps(report))
        self.assertNotIn("hourly_seconds", report)
        self.assertNotIn("minute_usage", report)

    def test_top_five_keeps_all_category_seconds_and_only_sends_ranked_apps(self):
        for n in range(1, 8):
            self.repo.add_usage(UsageDelta(f"tool{n}", n, self.now))
        local = build_ai_export(self.c, 1, False, now=self.now)["days"][0]
        self.assertEqual(len(local["apps"]), 7)
        self.service.sync()
        synced = next(iter(self.remote.pages.values()))["report"]
        self.assertEqual([row["app"] for row in synced["apps"]], [f"tool{n}" for n in (7, 6, 5, 4, 3)])
        self.assertEqual(sum(synced["categories_seconds"].values()), 28)
        self.assertNotIn("tool1", json.dumps(synced))

    def test_ranked_icons_are_uploaded_once_and_omitted_from_report_text(self):
        import base64
        from unittest.mock import patch
        client = NotionClient("test")
        raw = b"\x89PNG\r\n\x1a\nmock"
        icon = "data:image/png;base64," + base64.b64encode(raw).decode()
        with patch.object(client, "request", side_effect=[{"id": PARENT}, {}]) as request:
            report = client.prepare_record({"top_apps": [{"name": "A"}, {"name": "B", "icon": icon},
                                                         {"name": "C", "icon": icon}]})
        self.assertEqual(request.call_count, 2)
        self.assertIn(raw, request.call_args_list[1].args[2])
        self.assertEqual([f["name"] for f in report["_icon_files"]], ["top-02.png", "top-03.png"])
        self.assertNotIn("base64", json.dumps(report["top_apps"]))

    def test_sites_require_both_recording_and_export_opt_in(self):
        self.repo.add_domain_usage(DomainDelta("example.test", 7, self.now))
        self.assertEqual(build_ai_export(self.c, 1, True, now=self.now)["days"][0]["sites"], [])
        self.cfg.record_browser_enabled = True
        report = build_ai_export(self.c, 1, True, now=self.now)["days"][0]
        self.assertEqual(report["sites"], [{"domain": "example.test", "seconds": 7}])

    def test_dashboard_adds_devices_and_groups_weeks_across_new_year(self):
        from eye_care.services.notion_dashboard import DISPLAY_FIELDS, display_changes

        def record(key, day, seconds):
            fields = {n: {kind: False if kind == "checkbox" else None}
                      for n, kind in DISPLAY_FIELDS.items()}
            fields.update({"日期": {"date": {"start": day}}, "总秒数": {"number": seconds},
                           "记录": {"title": rich_text(key)}, "同步键": {"rich_text": rich_text(key)}})
            return {"id": key, "properties": fields}

        rows = [record("b", "2025-12-31", 3000), record("a", "2025-12-31", 7240),
                record("c", "2026-01-01", 3600), record("d", "2026-01-05", 59)]
        patch = dict(display_changes(rows))
        self.assertEqual(patch["a"]["同日其他秒数"]["number"], 3000)
        self.assertEqual(patch["a"]["记录"]["title"][0]["text"]["content"], "2小时50分")
        self.assertTrue(patch["b"]["日历明细行"]["checkbox"])
        self.assertEqual(patch["c"]["同周其他秒数"]["number"], 10240)
        self.assertTrue(patch["c"]["周趋势汇总行"]["checkbox"])
        self.assertEqual(patch["d"]["同周其他秒数"]["number"], 0)
        for row in rows:
            row["properties"].update(patch[row["id"]])
        self.assertEqual(list(display_changes(rows)), [])
        with self.assertRaises(NotionError):
            list(display_changes(rows + rows[:1]))

    def test_manual_sync_is_idempotent_and_updates_changed_day(self):
        self.usage(10)
        self.assertEqual(self.service.sync()["written"], 1)
        self.assertEqual(self.service.sync()["unchanged"], 1)
        self.usage(2)
        self.assertEqual(self.service.sync()["written"], 1)
        self.assertEqual((self.remote.created, self.remote.updated), (1, 1))
        self.assertEqual(next(iter(self.remote.pages.values()))["report"]["total_usage_seconds"], 12)

    def test_lost_local_state_discovers_and_updates_existing_remote_page(self):
        self.usage(10)
        self.service.sync()
        (self.root / "notion_sync_state.json").unlink()
        self.new_service().sync()
        self.assertEqual(len(self.remote.pages), 1)
        self.assertEqual(self.remote.updated, 0)

    def test_lost_post_response_does_not_duplicate_page_on_retry(self):
        self.usage(10)
        self.remote.lose_create_response = True
        with self.assertRaises(NotionError): self.service.sync()
        self.assertTrue(self.service.status()["last_error"])
        self.service.sync()
        self.assertEqual(len(self.remote.pages), 1)
        self.assertFalse(self.service.status()["last_error"])

    def test_ambiguous_creation_does_not_post_again_before_query_catches_up(self):
        self.usage(10)
        self.remote.lose_create_response = True
        with self.assertRaises(NotionError): self.service.sync()
        original = self.remote.find_day
        self.remote.find_day = lambda *a: None
        with self.assertRaises(NotionError): self.service.sync()
        self.assertEqual(self.remote.created, 1)
        self.remote.find_day = original
        self.service.sync()
        self.assertEqual(len(self.remote.pages), 1)

    def test_known_page_is_used_while_query_index_lags(self):
        self.usage(10)
        self.service.sync()
        self.remote.find_day = lambda *a: None
        self.usage(2)
        self.service.sync()
        self.assertEqual((self.remote.created, self.remote.updated), (1, 1))

    def test_second_service_refreshes_shared_state_before_syncing(self):
        second = self.new_service()
        self.usage(10)
        self.service.sync()
        self.remote.find_day = lambda *a: None
        self.usage(2)
        second.sync()
        self.assertEqual((self.remote.created, self.remote.updated), (1, 1))

    def test_excluded_app_is_removed_from_existing_remote_day(self):
        self.usage(10)
        self.service.sync()
        self.repo.delete_app_data("editor")
        self.service.sync()
        report = next(iter(self.remote.pages.values()))["report"]
        self.assertEqual(report["apps"], [])
        self.assertEqual(report["total_usage_seconds"], 0)

    def test_empty_days_are_not_uploaded_as_full_days_of_zero_use(self):
        self.cfg.notion_sync_days = 7
        result = self.service.sync()
        self.assertEqual(result["empty"], 7)
        self.assertEqual(self.remote.created, 0)

    def test_default_configuration_never_schedules_uploads(self):
        self.assertEqual(self.service.automatic_reason(self.now), "")
        self.assertFalse(self.cfg.notion_sync_daily)
        self.assertFalse(self.cfg.notion_sync_on_startup)

    def test_daily_job_catches_up_and_does_not_repeat_same_slot(self):
        self.cfg.notion_sync_daily = True
        self.cfg.notion_sync_time = "00:00"
        self.service._state["last_schedule_slot"] = self.service._slot(datetime.now().astimezone() - timedelta(days=1))
        self.assertEqual(self.service.automatic_reason(), "daily")
        self.usage(10)
        self.service.sync("daily")
        self.assertEqual(self.service.automatic_reason(), "")
        self.assertEqual(self.service.automatic_reason(datetime.now().astimezone() + timedelta(days=1)), "daily")

    def test_startup_sync_runs_once_per_process(self):
        self.cfg.notion_sync_on_startup = True
        self.assertEqual(self.service.automatic_reason(), "startup")
        self.assertEqual(self.service.automatic_reason(), "")
        self.service.stop()
        self.assertEqual(self.service.automatic_reason(), "")

    def test_new_daily_schedule_waits_until_next_due_time(self):
        values = self.service.settings()
        values.update(daily=True, time="23:00")
        self.service.save_settings(values)
        self.assertEqual(self.service.automatic_reason(), "")
        self.assertEqual(self.service.automatic_reason(datetime.now().astimezone() + timedelta(days=1)), "daily")

    def test_copied_device_identity_is_regenerated_for_machine_and_folder(self):
        first = installation_id(self.root, machine="computer-A")
        self.assertEqual(installation_id(self.root, machine="computer-A"), first)
        other = self.root / "copy"
        other.mkdir()
        shutil.copy2(self.root / "sync_device.json", other / "sync_device.json")
        self.assertNotEqual(installation_id(other, machine="computer-A"), first)
        self.assertNotEqual(installation_id(self.root, machine="computer-B"), first)

    def test_two_devices_same_day_never_overwrite_each_other(self):
        self.usage(10)
        self.service.sync()
        other = self.root / "second-install"
        other.mkdir()
        shutil.copy2(self.root / "sync_device.json", other / "sync_device.json")
        shutil.copy2(self.root / "device_id.txt", other / "device_id.txt")
        second_cfg = AppConfig(notion_parent_page=PARENT, notion_sync_days=1, notion_device_name="办公室")
        second = SimpleNamespace(data_dir=other, cfg_path=other / "config.json", cfg=second_cfg, repo=self.repo)
        service = NotionSyncService(second, credentials=self.creds, client_factory=lambda token: self.remote)
        service.sync()
        self.usage(2)
        service.sync()
        reports = [v["report"] for v in self.remote.pages.values()]
        self.assertEqual(len(reports), 2)
        self.assertEqual(sorted(r["total_usage_seconds"] for r in reports), [10, 12])
        self.assertEqual(len({r["device_id"] for r in reports}), 2)
        self.assertEqual(len({r["data_source_id"] for r in reports}), 1)

    def test_sync_lock_rejects_another_process_using_same_directory(self):
        with sync_directory_lock(self.root):
            with self.assertRaises(NotionError):
                self.service.sync()
        self.usage(10)
        self.assertEqual(self.service.sync()["written"], 1)

    def test_real_client_stops_on_duplicate_key_or_wrong_owner(self):
        client = NotionClient("test-only")
        client.request = lambda *a: {"results": [{"id": PARENT}, {"id": PARENT}]}
        with self.assertRaises(NotionError): client.find_day(PARENT, "key", "writer", self.day)
        client.request = lambda *a: {"results": [{"id": PARENT, "properties": {
            "设备ID": {"rich_text": rich_text("other-device")}, "日期": {"date": {"start": self.day}}}}]}
        with self.assertRaises(NotionError): client.find_day(PARENT, "key", "writer", self.day)

    def test_json_export_requires_no_notion_connection(self):
        self.usage(10)
        self.cfg.notion_parent_page = ""
        self.creds.clear()
        out = self.root / "ai.json"
        self.service.export_json(out)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["days"][0]["total_usage_seconds"], 10)
        self.assertEqual(self.remote.created, 0)

    def test_preview_cannot_save_clear_export_or_sync(self):
        service = self.new_service(persist=False)
        for action in (lambda: service.save_settings({}), service.clear_token,
                       lambda: service.export_json(self.root / "ai.json"), service.sync):
            with self.assertRaises(NotionError): action()
        self.assertTrue(self.creds.exists())

    def test_settings_keep_secret_out_of_config_and_require_valid_time(self):
        values = self.service.settings()
        values.update(time="25:00")
        with self.assertRaises(NotionError): self.service.save_settings(values, "new-fake-secret")
        values.update(time="23:00", daily=True)
        self.service.save_settings(values, "new-fake-secret")
        self.assertNotIn("new-fake-secret", self.c.cfg_path.read_text(encoding="utf-8"))
        self.service.clear_token()
        self.assertFalse(self.cfg.notion_sync_daily)

    def test_bad_sync_config_does_not_reset_unrelated_preferences(self):
        self.c.cfg_path.write_text(json.dumps({"notion_sync_days": "broken", "idle_threshold_s": 99}), encoding="utf-8")
        loaded = load_config(self.c.cfg_path)
        self.assertEqual(loaded.notion_sync_days, 7)
        self.assertEqual(loaded.idle_threshold_s, 99)

    def test_large_reports_split_notion_text_segments(self):
        text = "示例" * 3000
        segments = rich_text(text)
        self.assertTrue(all(len(p["text"]["content"]) <= 2000 for p in segments))
        self.assertEqual("".join(p["text"]["content"] for p in segments), text)

    @unittest.skipUnless(os.name == "nt", "Windows encryption")
    def test_windows_secret_storage_round_trip_is_not_plaintext(self):
        credentials = NotionCredentials(self.root)
        credentials.save("test-only-credential")
        self.assertNotIn(b"test-only-credential", credentials.path.read_bytes())
        self.assertEqual(credentials.load(), "test-only-credential")
        credentials.clear()
        self.assertFalse(credentials.exists())


if __name__ == "__main__":
    unittest.main()

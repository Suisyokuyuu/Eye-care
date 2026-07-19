from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from eye_care.data.json_wal_repo import JsonWalRepo
from eye_care.data.repository import DateRange, DomainDelta, UsageDelta


def _local_day(dt: datetime) -> str:
    """与 repo 内部一致地由 utc-aware 时间推导本地日期。"""
    return dt.astimezone().date().isoformat()


class DomainRepoTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        # 基准时间：固定 UTC 时刻（避免测试随实际时钟漂移）
        self.base = datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _repo(self) -> JsonWalRepo:
        return JsonWalRepo(self.data_dir)

    def _ts(self, minute_offset: int = 0, second: int = 0) -> datetime:
        return self.base + timedelta(minutes=minute_offset, seconds=second)

    # ---------------- 从未写过 domain：目录不存在、读返回 {} ----------------
    def test_never_written_dir_absent_and_reads_empty(self) -> None:
        repo = self._repo()
        self.assertFalse((self.data_dir / "minute_domains").exists())
        day = _local_day(self.base)
        self.assertEqual(repo.get_daily_domain_usage(day), {})
        self.assertEqual(
            repo.get_domain_usage_range(DateRange(day, _local_day(self.base + timedelta(days=3)))), {}
        )
        # 读操作不得创建目录
        self.assertFalse((self.data_dir / "minute_domains").exists())
        repo.close()

    # ---------------- 跨分钟 add → WAL 落盘 + daily cache 即时可读 ----------------
    def test_cross_minute_writes_wal_and_cache(self) -> None:
        repo = self._repo()
        day = _local_day(self.base)
        # 分钟 0 写两次
        repo.add_domain_usage(DomainDelta("example.com", 10, self._ts(0, 1)))
        repo.add_domain_usage(DomainDelta("example.com", 5, self._ts(0, 30)))
        repo.add_domain_usage(DomainDelta("google.com", 7, self._ts(0, 40)))
        # 首次写即创建目录
        self.assertTrue((self.data_dir / "minute_domains").exists())
        # 跨到分钟 1 → 触发 finalize，分钟 0 的桶写入 WAL
        repo.add_domain_usage(DomainDelta("example.com", 3, self._ts(1, 5)))

        wal = self.data_dir / "wal" / f"domains-{day}.jsonl"
        self.assertTrue(wal.exists(), "cross-minute finalize should flush WAL")

        # daily cache 即时反映所有累计（含当前未结算分钟）
        usage = repo.get_daily_domain_usage(day)
        self.assertEqual(usage["example.com"], 18)
        self.assertEqual(usage["google.com"], 7)
        repo.close()

    # ---------------- merge 幂等（跑两次结果一致）+ 主文件落盘 ----------------
    def test_merge_idempotent(self) -> None:
        repo = self._repo()
        day = _local_day(self.base)
        repo.add_domain_usage(DomainDelta("example.com", 10, self._ts(0, 1)))
        repo.add_domain_usage(DomainDelta("example.com", 20, self._ts(1, 1)))  # finalize 分钟0
        repo.add_domain_usage(DomainDelta("google.com", 5, self._ts(2, 1)))    # finalize 分钟1
        repo.merge()
        main = self.data_dir / "minute_domains" / f"domains-{day}.jsonl"
        self.assertTrue(main.exists())
        after_first = main.read_text(encoding="utf-8")
        # WAL 被清空
        self.assertFalse((self.data_dir / "wal" / f"domains-{day}.jsonl").exists())
        # 再跑一次 merge，主文件内容不变
        repo.merge()
        self.assertEqual(main.read_text(encoding="utf-8"), after_first)
        repo.close()

    # ---------------- get_daily / get_range 逐日累加正确 ----------------
    def test_daily_and_range(self) -> None:
        repo = self._repo()
        d0 = self.base
        d1 = self.base + timedelta(days=1)
        day0 = _local_day(d0)
        day1 = _local_day(d1)
        repo.add_domain_usage(DomainDelta("a.com", 100, d0))
        repo.add_domain_usage(DomainDelta("b.com", 40, d0 + timedelta(seconds=30)))
        repo.add_domain_usage(DomainDelta("a.com", 60, d1))
        repo.close()

        # 重开，从磁盘读回
        repo2 = self._repo()
        self.assertEqual(repo2.get_daily_domain_usage(day0), {"a.com": 100, "b.com": 40})
        self.assertEqual(repo2.get_daily_domain_usage(day1), {"a.com": 60})
        rng = repo2.get_domain_usage_range(DateRange(day0, day1))
        self.assertEqual(rng, {"a.com": 160, "b.com": 40})
        repo2.close()

    # ---------------- close() 结算残留（未跨分钟的）分钟 ----------------
    def test_close_finalizes_residual_minute(self) -> None:
        repo = self._repo()
        day = _local_day(self.base)
        # 全在同一分钟内，未触发跨分钟 finalize → 仅在 _cur_domains + cache
        repo.add_domain_usage(DomainDelta("x.com", 12, self._ts(0, 1)))
        repo.add_domain_usage(DomainDelta("x.com", 8, self._ts(0, 20)))
        # 此刻 WAL 尚无该分钟
        self.assertFalse((self.data_dir / "wal" / f"domains-{day}.jsonl").exists())
        repo.close()  # 应 finalize 残留分钟 → merge 到主文件

        repo2 = self._repo()
        self.assertEqual(repo2.get_daily_domain_usage(day), {"x.com": 20})
        repo2.close()

    # ---------------- 今天不被 LRU 淘汰（历史日历撑爆缓存不挤掉今天） ----------------
    def test_today_not_evicted_by_lru(self) -> None:
        repo = self._repo()
        # 用真实"现在"，让 local_day 与 _evict_oldest_day 的今天判定一致
        now = datetime.now(timezone.utc)
        today = _local_day(now)
        repo.add_domain_usage(DomainDelta("today.com", 99, now))
        # 查询大量历史日期（无数据），把 domain 缓存撑过上限
        base_day = now - timedelta(days=1)
        for i in range(1, 20):
            repo.get_daily_domain_usage(_local_day(base_day - timedelta(days=i)))
        # 今天仍在缓存且保有实时数据（未被淘汰/未被磁盘重载冲掉）
        self.assertEqual(repo.get_daily_domain_usage(today), {"today.com": 99})
        repo.close()

    # ---------------- app 维度在改动后行为不变 ----------------
    def test_app_dimension_unchanged(self) -> None:
        repo = self._repo()
        day = _local_day(self.base)
        repo.add_usage(UsageDelta("editor.exe", 30, self._ts(0, 1)))
        repo.add_usage(UsageDelta("editor.exe", 10, self._ts(1, 1)))  # finalize 分钟0
        repo.add_usage(UsageDelta("chrome.exe", 25, self._ts(2, 1)))
        self.assertEqual(repo.get_daily_usage(day), {"editor.exe": 40, "chrome.exe": 25})
        repo.merge()
        main = self.data_dir / "minute_usage" / f"minute-{day}.jsonl"
        self.assertTrue(main.exists())
        first = main.read_text(encoding="utf-8")
        repo.merge()
        self.assertEqual(main.read_text(encoding="utf-8"), first)  # app merge 仍幂等
        repo.close()

        repo2 = self._repo()
        rng = repo2.get_usage_range(DateRange(day, day))
        self.assertEqual(rng, {"editor.exe": 40, "chrome.exe": 25})
        repo2.close()

    # ---------------- app 与 domain 存储互不干扰（同 repo 并行写） ----------------
    def test_app_and_domain_isolated(self) -> None:
        repo = self._repo()
        day = _local_day(self.base)
        repo.add_usage(UsageDelta("chrome.exe", 50, self._ts(0, 1)))
        repo.add_domain_usage(DomainDelta("example.com", 30, self._ts(0, 1)))
        repo.add_usage(UsageDelta("chrome.exe", 20, self._ts(1, 1)))
        repo.add_domain_usage(DomainDelta("example.com", 15, self._ts(1, 1)))
        repo.close()

        repo2 = self._repo()
        self.assertEqual(repo2.get_daily_usage(day), {"chrome.exe": 70})
        self.assertEqual(repo2.get_daily_domain_usage(day), {"example.com": 45})
        # 主文件各自独立
        self.assertTrue((self.data_dir / "minute_usage" / f"minute-{day}.jsonl").exists())
        self.assertTrue((self.data_dir / "minute_domains" / f"domains-{day}.jsonl").exists())
        repo2.close()


    # ---------------- get_hourly_domain_breakdown：无目录返回 {}、有数据按小时聚合 ----------------
    def test_hourly_domain_breakdown_absent_dir(self) -> None:
        repo = self._repo()
        # 从未写过 domain → 目录不存在 → {}
        self.assertEqual(repo.get_hourly_domain_breakdown(_local_day(self.base)), {})
        self.assertFalse((self.data_dir / "minute_domains").exists())  # 读不建目录
        repo.close()

    def test_hourly_domain_breakdown_with_data(self) -> None:
        repo = self._repo()
        day = _local_day(self.base)
        # 同一本地小时内两个 domain，跨分钟触发 finalize 落 WAL
        repo.add_domain_usage(DomainDelta("a.com", 10, self._ts(0, 1)))
        repo.add_domain_usage(DomainDelta("b.com", 5, self._ts(0, 30)))
        repo.add_domain_usage(DomainDelta("a.com", 3, self._ts(1, 5)))  # finalize 分钟0
        repo.merge()  # 落主文件
        # 再写一条制造 WAL（验证主+WAL 都被读）
        repo.add_domain_usage(DomainDelta("a.com", 7, self._ts(2, 5)))
        repo.add_domain_usage(DomainDelta("a.com", 1, self._ts(3, 5)))  # finalize 分钟2

        bd = repo.get_hourly_domain_breakdown(day)
        # 基准时刻本地小时
        hour = int(self.base.astimezone().hour)
        self.assertIn(hour, bd)
        self.assertEqual(bd[hour].get("a.com"), 10 + 3 + 7)
        self.assertEqual(bd[hour].get("b.com"), 5)
        repo.close()


if __name__ == "__main__":
    unittest.main()

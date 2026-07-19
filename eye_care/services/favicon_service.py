"""浏览器 domain 统计 — favicon 抓取与磁盘/内存缓存服务（Step 6）。

设计要点（参考 `config_service.ConfigService.get_icon` 的应用图标缓存模式）：
  - `get_icon(domain)` 永不阻塞、永不在调用线程发网络请求：内存/磁盘命中直接返回
    `data:image/png;base64,...`；未命中则把 domain 入队交给**唯一的后台 daemon 线程**
    抓取，本次调用立即返回 `""`（下次 tick 再查大概率已经抓完）。
  - 抓取（标准库 urllib）：先 `https://<domain>/favicon.ico`；失败则拉首页 HTML 解析
    `<link rel="icon"|"shortcut icon"|"apple-touch-icon">`，`urljoin` 拼绝对地址再抓一次。
    任何异常都吞掉记为失败，绝不抛出；日志只允许出现 domain 与错误类型，不打印完整 URL。
  - 图像解码/缩放/落盘用 `PySide6.QtGui.QImage`（非 GUI 线程安全；**不用 QPixmap**）。
    本模块在开发机（Linux，无 PySide6）也必须能被 import——`QImage` 的 import 放在
    函数内部并用 try/except 保护，模块级绝不出现 `import PySide6`。
  - `icon_index.json` 记录每个 domain 的抓取结果，失败走**负缓存**指数退避
    （`next_retry_ts = now + min(6h*fail_count, 7天)`），未到期不再重复入队浪费网络。
    负缓存到期判断抽成纯函数 `_should_retry`，`parse_icon_links` 抽成模块级纯函数——
    两者都不发网络请求，供 `tests/test_favicon_parse.py` 直接测试。
"""
from __future__ import annotations

import base64
import hashlib
import html.parser
import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EyeCareFaviconFetcher/1.0"
_FAVICON_TIMEOUT_S = 4.0
_FAVICON_MAX_BYTES = 512 * 1024
_HTML_TIMEOUT_S = 4.0
_HTML_MAX_BYTES = 128 * 1024
_ICON_MAX_SIZE = 64

# 负缓存退避：失败次数 * 6 小时，封顶 7 天。
_NEG_CACHE_STEP_S = 6 * 3600
_NEG_CACHE_MAX_S = 7 * 24 * 3600

_ICON_RELS = {"icon", "apple-touch-icon", "apple-touch-icon-precomposed"}


class _IconLinkParser(html.parser.HTMLParser):
    """收集 `<link rel="icon"|"shortcut icon"|"apple-touch-icon" href=...>` 的 href。

    对 rel 大小写、多值（空格分隔，如 `"shortcut icon"`）容错；不抛异常（畸形 HTML
    由 `html.parser` 本身尽力解析，标签未闭合等不会中断 feed）。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "link":
            return
        attrs_d = {}
        for k, v in attrs:
            if k:
                attrs_d[k.lower()] = v or ""
        rel = attrs_d.get("rel", "")
        href = attrs_d.get("href", "")
        if not rel or not href:
            return
        rel_tokens = {t.strip().lower() for t in rel.split() if t.strip()}
        is_icon = bool(rel_tokens & _ICON_RELS) or ({"shortcut", "icon"} <= rel_tokens)
        if is_icon:
            self.hrefs.append(href)


def parse_icon_links(html_text: str, base_url: str) -> list:
    """从 HTML 文本中解析出候选 favicon 链接（按出现顺序的绝对 URL 列表）。

    纯函数：不发网络请求、不访问文件系统。畸形 HTML / 空输入不抛异常，返回 `[]`。
    """
    if not html_text:
        return []
    parser = _IconLinkParser()
    try:
        parser.feed(html_text)
    except Exception:  # noqa: BLE001 - 畸形 HTML 容错，绝不向上抛
        pass
    out = []
    for href in parser.hrefs:
        try:
            abs_url = urllib.parse.urljoin(base_url, href)
        except Exception:  # noqa: BLE001
            continue
        if abs_url:
            out.append(abs_url)
    return out


def _is_http_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _normalize_domain(domain) -> str:
    d = str(domain or "").strip().lower()
    if not d:
        return ""
    if "://" in d:
        d = d.split("://", 1)[1]
    d = d.split("/", 1)[0]
    return d


def _next_retry_delay_s(fail_count: int) -> float:
    """失败 `fail_count` 次后，距下次允许重试的等待秒数（封顶 7 天）。"""
    fc = max(1, int(fail_count or 0))
    return min(_NEG_CACHE_STEP_S * fc, _NEG_CACHE_MAX_S)


def _should_retry(entry: Optional[dict], now: float) -> bool:
    """负缓存条目 `entry`（失败记录）在时刻 `now` 是否已到期、可以重新入队抓取。

    纯函数：`entry` 为空（从未失败过）视为可重试；否则按 `next_retry_ts` 判断。
    仅用于**失败**条目——成功（`ok=True`）条目的取用逻辑在 `FaviconService.get_icon`
    里单独处理（磁盘文件缺失时无视退避直接重新入队，因为那是本地缓存损坏而非远端失败）。
    """
    if not entry:
        return True
    next_retry_ts = entry.get("next_retry_ts")
    if not next_retry_ts:
        return True
    return now >= float(next_retry_ts)


class FaviconService:
    """domain → favicon 的惰性抓取 + 磁盘/内存缓存服务。

    公共 API：
      - `get_icon(domain: str) -> str`：非阻塞。命中返回
        `"data:image/png;base64,..."`；未命中入队后台抓取并返回 `""`。
      - `stop(timeout_s: float = 2.0) -> None`：停止后台 worker（daemon 线程，
        进程退出时也会自动结束，`stop` 用于测试/优雅关闭场景）。
    """

    def __init__(self, data_dir: Path, log: Optional[logging.Logger] = None) -> None:
        self._data_dir = Path(data_dir)
        self._icons_dir = self._data_dir / "domain_icons"
        self._index_path = self._icons_dir / "icon_index.json"
        self._log = log or globals()["log"]

        self._lock = threading.Lock()
        self._mem_cache: dict = {}          # domain -> data url（仅正向命中）
        self._index: Optional[dict] = None  # 惰性加载

        self._queue: "queue.Queue" = queue.Queue()
        self._queued: set = set()
        self._worker: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()

    # ------------------------------------------------------------------
    # 目录 / 索引（惰性创建，线程间用 self._lock 互斥）
    # ------------------------------------------------------------------
    def _ensure_dirs(self) -> None:
        try:
            self._icons_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._log.debug("favicon: mkdir failed: %s", type(exc).__name__)

    def _load_index(self) -> dict:
        with self._lock:
            if self._index is not None:
                return self._index
            idx: dict = {}
            if self._index_path.exists():
                try:
                    idx = json.loads(self._index_path.read_text(encoding="utf-8") or "{}")
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
                    self._log.debug("favicon: index read failed: %s", type(exc).__name__)
                    idx = {}
            if not isinstance(idx, dict):
                idx = {}
            self._index = idx
            return idx

    def _save_index_locked(self) -> None:
        """写索引到磁盘。调用方必须已持有 `self._lock`。"""
        try:
            self._ensure_dirs()
            self._index_path.write_text(
                json.dumps(self._index or {}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            self._log.debug("favicon: index write failed: %s", type(exc).__name__)

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def get_icon(self, domain: str) -> str:
        dom = _normalize_domain(domain)
        if not dom:
            return ""

        with self._lock:
            cached = self._mem_cache.get(dom)
        if cached:
            return cached

        idx = self._load_index()
        with self._lock:
            entry = idx.get(dom)
            entry = dict(entry) if isinstance(entry, dict) else None

        need_fetch = True
        if entry and entry.get("ok") and entry.get("file"):
            data_url = self._read_png_as_data_url(str(entry["file"]))
            if data_url:
                with self._lock:
                    self._mem_cache[dom] = data_url
                return data_url
            # 索引说成功了，但磁盘文件缺失（缓存损坏）——无视退避，直接重新抓取。
            need_fetch = True
        elif entry and not entry.get("ok"):
            need_fetch = _should_retry(entry, time.time())
        # entry is None -> 从未尝试过，需要抓取

        if not need_fetch:
            return ""

        with self._lock:
            already_queued = dom in self._queued
            if not already_queued:
                self._queued.add(dom)
        if not already_queued:
            self._ensure_worker()
            try:
                self._queue.put_nowait(dom)
            except Exception:  # noqa: BLE001
                with self._lock:
                    self._queued.discard(dom)
        return ""

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop_evt.set()
        try:
            self._queue.put_nowait(None)  # 唤醒阻塞在 get() 上的 worker
        except Exception:  # noqa: BLE001
            pass
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=timeout_s)

    # ------------------------------------------------------------------
    # worker 线程
    # ------------------------------------------------------------------
    def _ensure_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop_evt.clear()
        self._worker = threading.Thread(target=self._worker_loop, name="FaviconWorker", daemon=True)
        self._worker.start()

    def _worker_loop(self) -> None:
        while not self._stop_evt.is_set():
            try:
                dom = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if dom is None:
                break
            try:
                self._fetch_and_cache(dom)
            except Exception as exc:  # noqa: BLE001 - 单个 domain 出错不能拖垮 worker
                self._log.debug("favicon: worker error domain=%s err=%s", dom, type(exc).__name__)
            finally:
                with self._lock:
                    self._queued.discard(dom)
                self._queue.task_done()

    def _fetch_and_cache(self, domain: str) -> None:
        now = time.time()
        idx = self._load_index()
        with self._lock:
            entry = dict(idx.get(domain) or {})
        fail_count = int(entry.get("fail_count", 0) or 0)

        png_bytes = self._download_favicon_bytes(domain)
        file_name = hashlib.sha1(domain.encode("utf-8")).hexdigest() + ".png"

        ok = False
        if png_bytes:
            ok = self._save_png(file_name, png_bytes)

        if ok:
            new_entry = {
                "file": file_name,
                "ok": True,
                "ts": now,
                "fail_count": 0,
                "next_retry_ts": 0,
            }
        else:
            fail_count += 1
            new_entry = {
                "file": entry.get("file", ""),
                "ok": False,
                "ts": now,
                "fail_count": fail_count,
                "next_retry_ts": now + _next_retry_delay_s(fail_count),
            }

        with self._lock:
            idx[domain] = new_entry
            self._index = idx
            self._save_index_locked()

        if ok:
            data_url = self._read_png_as_data_url(file_name)
            if data_url:
                with self._lock:
                    self._mem_cache[domain] = data_url
        else:
            self._log.debug("favicon: fetch failed domain=%s", domain)

    # ------------------------------------------------------------------
    # 网络 + 图像处理（仅在 worker 线程调用）
    # ------------------------------------------------------------------
    def _download_favicon_bytes(self, domain: str) -> Optional[bytes]:
        # 1) 直接尝试 /favicon.ico
        raw = self._http_get(f"https://{domain}/favicon.ico", domain, _FAVICON_TIMEOUT_S, _FAVICON_MAX_BYTES)
        img = self._decode_and_normalize(raw) if raw else None
        if img:
            return img

        # 2) 失败则拉首页 HTML，解析 <link icon> 候选
        html_bytes = self._http_get(f"https://{domain}/", domain, _HTML_TIMEOUT_S, _HTML_MAX_BYTES)
        if not html_bytes:
            return None
        try:
            html_text = html_bytes.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return None

        for candidate_url in parse_icon_links(html_text, f"https://{domain}/"):
            if not _is_http_url(candidate_url):
                continue
            raw2 = self._http_get(candidate_url, domain, _FAVICON_TIMEOUT_S, _FAVICON_MAX_BYTES)
            img2 = self._decode_and_normalize(raw2) if raw2 else None
            if img2:
                return img2
        return None

    def _http_get(self, url: str, domain: str, timeout_s: float, max_bytes: int) -> Optional[bytes]:
        if not _is_http_url(url):
            return None
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return resp.read(max_bytes)
        except Exception as exc:  # noqa: BLE001 - 任何抓取异常吞掉，日志不带完整 URL
            self._log.debug("favicon: http get failed domain=%s err=%s", domain, type(exc).__name__)
            return None

    @staticmethod
    def _decode_and_normalize(data: Optional[bytes]) -> Optional[bytes]:
        """bytes（.ico/.png/...）→ 等比缩到 <=64px 的 PNG bytes。解码失败返回 None。

        `QImage` 在非 GUI 线程安全（严禁用 `QPixmap`）。import 放函数内部 + try/except，
        本机（Linux 无 PySide6）不会因此炸模块；仅在真正跑到这里（worker 线程，生产环境
        有 PySide6）才会执行。
        """
        if not data:
            return None
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QImage
        except Exception:  # noqa: BLE001 - 无 PySide6 环境按解码失败处理
            return None

        import os
        import tempfile

        try:
            img = QImage()
            if not img.loadFromData(data) or img.isNull():
                return None
            if img.width() > _ICON_MAX_SIZE or img.height() > _ICON_MAX_SIZE:
                img = img.scaled(
                    _ICON_MAX_SIZE, _ICON_MAX_SIZE,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation,
                )
            fd, tmp_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            try:
                if not img.save(tmp_path, "PNG"):
                    return None
                return Path(tmp_path).read_bytes()
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except Exception:  # noqa: BLE001 - 解码/缩放任何异常都按失败处理
            return None

    def _save_png(self, filename: str, data: bytes) -> bool:
        try:
            self._ensure_dirs()
            (self._icons_dir / filename).write_bytes(data)
            return True
        except OSError as exc:
            self._log.debug("favicon: save png failed: %s", type(exc).__name__)
            return False

    def _read_png_as_data_url(self, filename: str) -> str:
        if not filename:
            return ""
        try:
            raw = (self._icons_dir / filename).read_bytes()
        except OSError:
            return ""
        return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")

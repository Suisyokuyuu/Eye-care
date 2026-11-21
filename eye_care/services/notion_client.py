"""Small, credential-safe Notion REST client; writes are never blindly retried."""
from __future__ import annotations

import base64
import json
import re
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NotionError(RuntimeError):
    def __init__(self, message, *, status=None):
        super().__init__(message)
        self.status = status


DATABASE_TITLE = "EyE Care · 每日数据仓库（正式版）"
DATABASE_TITLES = {DATABASE_TITLE, "EyE Care · 每日数据仓库", "EyE Care · 每日使用汇总"}
DAILY_SCHEMA = {**{k: "rich_text" for k in (
    "设备", "总时长", "应用汇总", "分类汇总", "网站汇总", "同步键", "设备ID", "数据源ID", "内容指纹")},
    **{k: "number" for k in ("使用分钟", "总秒数", "休息完成", "休息开始", "跳过休息")},
    "记录": "title", "日期": "date", "最近同步": "date", "记录状态": "select", "数据类型": "select"}


def property_text(row, name):
    prop = row.get("properties", {}).get(name, {})
    return "".join(p.get("plain_text", p.get("text", {}).get("content", ""))
                   for p in prop.get("rich_text", prop.get("title", [])))


def duration_text(seconds):
    seconds = max(0, int(seconds))
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours}小时 {minutes}分" if hours else (f"{minutes}分" if minutes else f"{seconds}秒")


def daily_properties(report, digest):
    day, name = report["local_date"], report["device_name"]
    total = report["total_usage_seconds"]
    events = report["rest_event_counts"]
    app_text = "；".join(f"{r['name']}（{r.get('category') or '未分类'}）{duration_text(r['seconds'])}" for r in report["apps"])
    category_text = "；".join(f"{k} {duration_text(v)}" for k, v in report["categories_seconds"].items())
    sites = "；".join(f"{r['domain']} {duration_text(r['seconds'])}" for r in report["sites"])
    values = {"设备": name, "总时长": duration_text(total), "应用汇总": app_text,
              "分类汇总": category_text, "网站汇总": sites, "同步键": report["sync_key"],
              "设备ID": report["device_id"], "数据源ID": report["data_source_id"], "内容指纹": digest}
    result = {k: {"rich_text": rich_text(v)} for k, v in values.items()}
    if "_icon_files" in report:
        result["应用图标"] = {"files": report["_icon_files"]}
    result.update({k: {"number": v} for k, v in {
        "总秒数": total, "使用分钟": round(total / 60, 2), "休息完成": events["rest_complete"],
        "休息开始": events["rest_begin"], "跳过休息": events["rest_snooze"]}.items()})
    state = ("今日进行中" if report["day_state"] == "today_so_far" else "历史记录") if report["has_records"] else "无记录"
    result.update({"记录": {"title": rich_text(f"{duration_text(total)} · {name} · {day}")},
                   "日期": {"date": {"start": day}}, "最近同步": {"date": {"start": report["exported_at"]}},
                   "记录状态": {"select": {"name": state}},
                   "数据类型": {"select": {"name": report.get("data_kind", "正式数据")}}})
    return result


def page_id(value: str) -> str:
    value = str(value or "").strip()
    path = urlsplit(value).path if "://" in value else value
    match = re.search(r"([a-fA-F0-9]{32}|[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12})/?$", path)
    if not match:
        raise NotionError("请填写有效的 Notion 页面链接。")
    return str(uuid.UUID(match.group(1)))


def rich_text(text: str) -> list:
    # Notion limits each text segment to 2,000 characters.
    parts = [text[i:i + 1800] for i in range(0, len(text), 1800)] or [""]
    if len(parts) > 100:
        raise NotionError("当天统计内容过大，请先使用 JSON 文件导出。")
    return [{"type": "text", "text": {"content": part}} for part in parts]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class NotionClient:
    def __init__(self, token: str):
        self._token = token
        self._opener = build_opener(_NoRedirect())
        self._last_request = 0.0
        self._icon_uploads = {}
        self._source_schema = {}

    def request(self, method: str, path: str, body=None, *, content_type="application/json") -> dict:
        delay = 0.36 - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        data = body if body is None or isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = Request("https://api.notion.com/v1" + path, data=data, method=method, headers={
            "Authorization": "Bearer " + self._token, "Notion-Version": "2026-03-11",
            "Content-Type": content_type,
        })
        self._last_request = time.monotonic()
        try:
            with self._opener.open(req, timeout=20) as response:
                return json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))
        except HTTPError as exc:
            hints = {
                400: "Notion 未接受数据格式。", 401: "密钥无效，请重新填写。",
                402: "Notion 工作区额度不足。", 403: "没有读写权限，或工作区内容额度已用尽。",
                404: "页面不存在或未授权，请在 Notion 页面的“连接”中添加此 API 连接。",
                429: "Notion 请求限流，请稍后重试。", 529: "Notion 暂时繁忙，请稍后重试。",
            }
            # Never expose remote error bodies, request headers, or credentials.
            raise NotionError(hints.get(exc.code, f"Notion 服务暂时不可用（HTTP {exc.code}）。"), status=exc.code) from None
        except (URLError, TimeoutError, OSError):
            raise NotionError("连接 Notion 失败或超时；请检查网络后重试，不会自动重复创建记录。") from None
        except (ValueError, UnicodeError):
            raise NotionError("Notion 返回内容无法解析，请稍后重试。") from None

    def children(self, block_id: str) -> list:
        rows, cursor = [], None
        seen = set()
        while True:
            query = {"page_size": 100}
            if cursor:
                query["start_cursor"] = cursor
            result = self.request("GET", f"/blocks/{page_id(block_id)}/children?{urlencode(query)}")
            rows.extend(result.get("results", []))
            if not result.get("has_more"):
                return rows
            cursor = result.get("next_cursor")
            if not cursor or cursor in seen:
                raise NotionError("Notion 分页响应异常，请稍后重试。")
            seen.add(cursor)

    def resolve_source(self, destination):
        target = page_id(destination)
        try:
            database = self.request("GET", f"/databases/{target}")
        except NotionError as exc:
            if exc.status not in (400, 404):
                raise
            candidates = [b for b in self.children(target) if b.get("type") == "child_database"
                          and b.get("child_database", {}).get("title") in DATABASE_TITLES
                          and not b.get("archived") and not b.get("in_trash")]
            if len(candidates) > 1:
                raise NotionError("该页面有多个同名统计库，请直接填写要使用的数据库链接。")
            if candidates:
                database = self.request("GET", f"/databases/{page_id(candidates[0]['id'])}")
            else:
                # The containing page has already been read successfully. Never retry POST.
                database = self.request("POST", "/databases", {
                    "parent": {"type": "page_id", "page_id": target}, "title": rich_text(DATABASE_TITLE),
                    "initial_data_source": {"properties": {k: {v: {}} for k, v in DAILY_SCHEMA.items()}}})
        candidates = []
        for item in database.get("data_sources", []):
            source = self.request("GET", f"/data_sources/{page_id(item['id'])}")
            props = source.get("properties", {})
            if all(props.get(k, {}).get("type") == t for k, t in DAILY_SCHEMA.items()):
                candidates.append(page_id(source["id"]))
                compatible_properties = props
        if len(candidates) != 1:
            raise NotionError("统计库字段不匹配或有多个数据源，请使用 EyE Care 每日使用汇总数据库。")
        source_id = candidates[0]
        icon_type = compatible_properties.get("应用图标", {}).get("type")
        if icon_type is None:
            self.request("PATCH", f"/data_sources/{source_id}", {"properties": {"应用图标": {"files": {}}}})
        elif icon_type != "files":
            raise NotionError("统计库的“应用图标”需要使用文件类型。")
        self._source_schema = compatible_properties
        return source_id, page_id(database["id"])

    def refresh_dashboard(self, source, days, changed_totals):
        from .notion_dashboard import refresh_calendar
        return refresh_calendar(self, source, self._source_schema, days, changed_totals)

    def prepare_record(self, report):
        files = []
        top = []
        for rank, entry in enumerate(report.get("top_apps", []), 1):
            row = {k: v for k, v in entry.items() if k != "icon"}
            icon = entry.get("icon") or ""
            if icon.startswith("data:image/png;base64,"):
                raw = base64.b64decode(icon.partition(",")[2], validate=True)
                if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) <= 256 * 1024:
                    filename = f"top-{rank:02}.png"
                    if raw not in self._icon_uploads:
                        upload = self.request("POST", "/file_uploads", {
                            "mode": "single_part", "filename": filename, "content_type": "image/png"})
                        upload_id = page_id(upload["id"])
                        boundary = uuid.uuid4().hex
                        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                                f'filename="{filename}"\r\nContent-Type: image/png\r\n\r\n').encode()
                        self.request("POST", f"/file_uploads/{upload_id}/send",
                                     body + raw + f"\r\n--{boundary}--\r\n".encode(),
                                     content_type=f"multipart/form-data; boundary={boundary}")
                        self._icon_uploads[raw] = upload_id
                    files.append({"name": filename, "type": "file_upload",
                                  "file_upload": {"id": self._icon_uploads[raw]}})
                    row["icon_file"] = filename
            top.append(row)
        return {**report, "top_apps": top, "_icon_files": files}

    def find_day(self, source, key, device, day):
        result = self.request("POST", f"/data_sources/{page_id(source)}/query", {
            "filter": {"property": "同步键", "rich_text": {"equals": key}}, "page_size": 2})
        rows = result.get("results", [])
        if len(rows) > 1 or result.get("has_more"):
            raise NotionError("该日期和设备有重复记录，已停止同步；请在 Notion 中整理重复行后重试。")
        if not rows:
            return None
        row = rows[0]
        self._check_owner(row, key, device, day)
        return row

    @staticmethod
    def _check_owner(row, key, device, day):
        if (property_text(row, "设备ID") != device or
                property_text(row, "同步键") != key or
                (row.get("properties", {}).get("日期", {}).get("date") or {}).get("start") != day):
            raise NotionError("远端记录的设备或日期不匹配，已停止更新以保护其他设备的数据。")

    def get_record(self, source, target, key, device, day):
        try:
            row = self.request("GET", f"/pages/{page_id(target)}")
        except NotionError as exc:
            if exc.status == 404:
                return None
            raise
        if row.get("archived") or row.get("in_trash"):
            return None
        if row.get("parent", {}).get("data_source_id") != page_id(source):
            raise NotionError("原统计记录已移动到其他位置，请先确认 Notion 中的记录归属。")
        self._check_owner(row, key, device, day)
        return row

    def _record_properties(self, report, digest, *, creating):
        props = daily_properties(report, digest)
        if self._source_schema.get("日历明细行", {}).get("type") == "checkbox":
            if creating:
                props["记录"] = {"title": rich_text(duration_text(report["total_usage_seconds"]).replace(" ", ""))}
            else:
                # The calendar owns this label, which can include other devices.
                props.pop("记录")
        return props

    def create_record(self, source, report, digest):
        public_report = {k: v for k, v in report.items() if k != "_icon_files"}
        result = self.request("POST", "/pages", {
            "parent": {"type": "data_source_id", "data_source_id": page_id(source)},
            "properties": self._record_properties(report, digest, creating=True),
            "children": [{"object": "block", "type": "code", "code": {
                "rich_text": rich_text(json.dumps(public_report, ensure_ascii=False, indent=2)), "language": "json"}}]})
        return page_id(result.get("id", ""))

    def update_record(self, target, report, digest):
        # Update only the managed JSON block; leave user notes on the row untouched.
        self.update_day(target, {k: v for k, v in report.items() if k != "_icon_files"})
        self.request("PATCH", f"/pages/{page_id(target)}", {"properties": self._record_properties(report, digest, creating=False)})

    def create_day(self, parent: str, title: str, report: dict) -> str:
        result = self.request("POST", "/pages", {
            "parent": {"type": "page_id", "page_id": page_id(parent)},
            "properties": {"title": {"title": rich_text(title)}},
            "children": [{"object": "block", "type": "code", "code": {
                "rich_text": rich_text(json.dumps(report, ensure_ascii=False, indent=2)), "language": "json",
            }}],
        })
        return page_id(result.get("id", ""))

    def update_day(self, target: str, report: dict):
        for block in self.children(target):
            if block.get("type") != "code":
                continue
            try:
                old = json.loads("".join(p.get("plain_text", p.get("text", {}).get("content", ""))
                                        for p in block["code"].get("rich_text", [])))
            except (ValueError, TypeError):
                continue
            if isinstance(old, dict) and all(old.get(k) == report.get(k) for k in ("schema", "device_id", "local_date")):
                self.request("PATCH", f"/blocks/{page_id(block['id'])}", {"code": {
                    "rich_text": rich_text(json.dumps(report, ensure_ascii=False, indent=2)), "language": "json",
                }})
                return
        raise NotionError("同名页面中没有本软件的统计记录，已停止更新以保护页面内容。")

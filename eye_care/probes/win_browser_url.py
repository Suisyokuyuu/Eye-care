from __future__ import annotations

"""Windows 浏览器地址栏 URL → domain 采集探针（UI Automation，手写 comtypes 客户端）。

隐私硬约束（最高优先级）：
  - 完整 URL 只允许存在于 worker 线程「读值 → extract_domain」这一段调用栈内；
  - 绝不存成成员变量、绝不进任何日志（含 debug 级）、绝不跨线程传递原始 URL；
  - 共享状态只保存已剥离的 domain + hwnd + 采样时间戳。

跨平台约束：本文件顶层只 import 标准库 + 纯函数 extract_domain（Linux 安全）。
comtypes / ctypes.windll 的一切引用都延迟到 worker 线程内首次使用；进程内其它线程
不碰 COM。非 Windows 环境即使误 import 本模块也不会在 import 期报错。
"""

import threading
import time

from ..utils.url_domain import extract_domain


# ---- UI Automation 常量（数值 + 命名常量注释；worker 内以生成模块 getattr 兜底数值） ----
_UIA_EditControlTypeId = 50004               # UIA_EditControlTypeId
_UIA_ControlTypePropertyId = 30003           # UIA_ControlTypePropertyId
_UIA_IsValuePatternAvailablePropertyId = 30043  # UIA_IsValuePatternAvailablePropertyId
_UIA_ValueValuePropertyId = 30045            # UIA_ValueValuePropertyId
_UIA_HasKeyboardFocusPropertyId = 30008      # UIA_HasKeyboardFocusPropertyId
_TreeScope_Descendants = 4                   # TreeScope_Descendants

# COINIT_MULTITHREADED = 0x0
_COINIT_MULTITHREADED = 0x0

# 采样节流参数
_SAMPLE_INTERVAL_S = 2.0      # active 时每 2s 采样一次
_IDLE_POLL_S = 0.5            # 非 active 时每 0.5s 轮询 flag，零 UIA 调用
_DOWNGRADE_INTERVAL_S = 10.0  # 同一 hwnd 连续失败后降频
_MAX_HWND_FAILS = 3           # 连续 3 次异常/找不到 → 降频


def _const(mod, name: str, default: int) -> int:
    try:
        return int(getattr(mod, name, default))
    except Exception:
        return int(default)


class BrowserUrlWatcher:
    """在独立 daemon 线程内用 UIA 采集前台浏览器地址栏 domain。

    tick 每秒通过 set_active() 喂状态（前台是浏览器且开关开 → True），
    worker 按节流策略采样，get_domain() 返回最近一次（未过期的）domain。
    """

    def __init__(self, log=None) -> None:
        self._log = log
        self._stop_evt = threading.Event()
        self._thr = None  # type: ignore[assignment]
        self._active = False  # 由 set_active 置位，worker 读取；bool 赋值原子，无需锁

        # 共享状态（_state_lock 保护）：仅 domain / hwnd / 采样时间戳，绝无原始 URL
        self._state_lock = threading.Lock()
        self._domain = ""
        self._hwnd = 0
        self._ts = 0.0  # time.monotonic() 采样时刻

        # 以下字段仅 worker 线程自用（无需锁）
        self._cache_hwnd = 0
        self._cache_edit = None
        self._hwnd_fail = 0
        self._next_wait_s = _SAMPLE_INTERVAL_S
        self._com_inited = False  # 本线程是否由我们 CoInitializeEx 成功（对称 CoUninitialize 用）

    # ----- 对外接口 -----
    def start(self) -> None:
        if self._thr is not None:
            return
        self._stop_evt.clear()
        self._thr = threading.Thread(
            target=self._run, daemon=True, name="browser_url_watcher"
        )
        self._thr.start()

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop_evt.set()
        thr = self._thr
        if thr is not None:
            try:
                thr.join(timeout=timeout_s)
            except Exception:
                pass
        self._thr = None

    def set_active(self, active: bool) -> None:
        # tick 每秒调用：仅设 flag，零阻塞、零 UIA 调用。
        self._active = bool(active)

    def get_domain(self, max_age_s: float = 6.0) -> str:
        with self._state_lock:
            dom = self._domain
            ts = self._ts
        if not dom:
            return ""
        if time.monotonic() - ts > max_age_s:
            return ""
        return dom

    # ----- worker 线程内部 -----
    def _run(self) -> None:
        import ctypes  # windll 只在 worker 线程内触碰

        try:
            uia = None  # 延迟到首次 active 时创建
            consts = None
            user32 = None
            try:
                user32 = ctypes.windll.user32
                # HWND 是指针宽度；默认 restype=c_int 在 x64 上可能截断/变负
                user32.GetForegroundWindow.restype = ctypes.c_void_p
            except Exception:
                user32 = None

            while not self._stop_evt.is_set():
                if not self._active or user32 is None:
                    if self._stop_evt.wait(_IDLE_POLL_S):
                        break
                    continue

                if uia is None:
                    uia, consts = self._create_uia()
                    if uia is None:
                        # COM/UIA 起不来 → 降级：慢轮询，不刷日志刷屏
                        if self._stop_evt.wait(_SAMPLE_INTERVAL_S):
                            break
                        continue

                self._next_wait_s = _SAMPLE_INTERVAL_S
                try:
                    self._sample_once(user32, uia, consts)
                except Exception as e:
                    # 任何 COM 异常吞掉降级；只可记 hwnd/错误类型，绝不记 URL
                    self._note_failure(exc=e)

                if self._stop_evt.wait(self._next_wait_s):
                    break
        finally:
            if self._com_inited:
                try:
                    import comtypes
                    comtypes.CoUninitialize()
                except Exception:
                    pass

    def _create_uia(self):
        """在 worker 线程内首次创建 UIA 客户端 + 解析常量。失败返回 (None, None)。

        COM 初始化坑（务必保持此顺序，勿回退成手动 ole32.CoInitializeEx）：
        comtypes **在 import 时**就会对当前线程 CoInitializeEx（模型取 sys.coinit_flags，
        默认 STA）。若本线程已被按其它模型初始化，import 会直接抛 RPC_E_CHANGED_MODE。
        因此：① 首次 import 前把 sys.coinit_flags 设为 MTA；② import 后再显式
        comtypes.CoInitializeEx 确保**本线程**已初始化（import 可能早已发生在别的线程，
        那次初始化不属于本线程）；③ RPC_E_CHANGED_MODE 容忍——本线程已是 STA 也能跑 UIA。
        """
        try:
            import sys as _sys

            if "comtypes" not in _sys.modules:
                _sys.coinit_flags = _COINIT_MULTITHREADED  # 须在首次 import comtypes 前设置
            import comtypes
            import comtypes.client

            try:
                comtypes.CoInitializeEx(_COINIT_MULTITHREADED)
                self._com_inited = True
            except OSError:
                # RPC_E_CHANGED_MODE：本线程已按 STA 初始化（如 import 就发生在本线程且
                # coinit_flags 已被别处设过）——UIA 客户端 STA 亦可用，沿用即可。
                pass

            mod = comtypes.client.GetModule("UIAutomationCore.dll")
            uia = comtypes.client.CreateObject(
                mod.CUIAutomation, interface=mod.IUIAutomation
            )
            consts = {
                "edit_type": _const(mod, "UIA_EditControlTypeId", _UIA_EditControlTypeId),
                "ctrl_type_prop": _const(mod, "UIA_ControlTypePropertyId", _UIA_ControlTypePropertyId),
                "is_value_avail_prop": _const(mod, "UIA_IsValuePatternAvailablePropertyId", _UIA_IsValuePatternAvailablePropertyId),
                "value_value_prop": _const(mod, "UIA_ValueValuePropertyId", _UIA_ValueValuePropertyId),
                "has_focus_prop": _const(mod, "UIA_HasKeyboardFocusPropertyId", _UIA_HasKeyboardFocusPropertyId),
                "scope_desc": _const(mod, "TreeScope_Descendants", _TreeScope_Descendants),
            }
            return uia, consts
        except Exception as e:
            # 创建阶段无任何 URL，记 repr 便于定位（如 RPC_E_CHANGED_MODE / gen 缓存写失败）
            self._debug("browser_url worker: UIA 创建失败 %s: %r", type(e).__name__, e)
            return None, None

    def _sample_once(self, user32, uia, consts) -> None:
        hwnd = int(user32.GetForegroundWindow() or 0)
        if not hwnd:
            return

        # hwnd 变化：重置缓存（Edit 元素 + 失败计数），换 hwnd 重置降频
        if hwnd != self._cache_hwnd:
            self._cache_hwnd = hwnd
            self._cache_edit = None
            self._hwnd_fail = 0

        edit = self._cache_edit
        if edit is None:
            edit = self._find_edit(uia, consts, hwnd)
            if edit is None:
                self._note_failure()
                return
            self._cache_edit = edit
            self._hwnd_fail = 0

        # 读值前查键盘焦点：地址栏有焦点=用户正在输入 → 跳过本次（保留上次值/不更新时间戳）
        try:
            focused = edit.GetCurrentPropertyValue(consts["has_focus_prop"])
        except Exception as e:
            self._cache_edit = None
            self._note_failure(exc=e)
            return
        if focused:
            return

        try:
            raw = edit.GetCurrentPropertyValue(consts["value_value_prop"])
        except Exception as e:
            self._cache_edit = None
            self._note_failure(exc=e)
            return

        # 完整 URL 只在此处栈内存在，立即抽取 domain，绝不落成员/日志
        raw_str = raw if isinstance(raw, str) else ""
        dom = extract_domain(raw_str)
        del raw, raw_str  # 尽早释放对原始 URL 的引用

        # 有效读取即视为成功，重置失败计数
        self._hwnd_fail = 0
        if dom:
            with self._state_lock:
                self._domain = dom
                self._hwnd = hwnd
                self._ts = time.monotonic()
        # dom 为空（内部页 / 搜索词）：不更新，旧值自然过期即可

    def _find_edit(self, uia, consts, hwnd):
        root = uia.ElementFromHandle(hwnd)
        if not root:
            return None
        cond_type = uia.CreatePropertyCondition(
            consts["ctrl_type_prop"], consts["edit_type"]
        )
        cond_val = uia.CreatePropertyCondition(
            consts["is_value_avail_prop"], True
        )
        cond = uia.CreateAndCondition(cond_type, cond_val)
        edit = root.FindFirst(consts["scope_desc"], cond)
        if not edit:
            return None
        return edit

    def _note_failure(self, exc=None) -> None:
        self._hwnd_fail += 1
        if self._hwnd_fail >= _MAX_HWND_FAILS:
            self._next_wait_s = _DOWNGRADE_INTERVAL_S
        if exc is not None:
            # 失败日志只可记 hwnd / 错误类型码，绝不记 URL（COMError 的 args 只含 HRESULT/接口信息）
            self._debug("browser_url worker: sample 失败 hwnd=%s err=%s",
                        self._cache_hwnd, type(exc).__name__)

    def _debug(self, fmt: str, *args) -> None:
        if self._log is not None:
            try:
                self._log.debug(fmt, *args)
            except Exception:
                pass

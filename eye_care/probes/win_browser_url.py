from __future__ import annotations

"""Windows 浏览器 URL → domain 采集探针（UI Automation，手写 comtypes 客户端）。

取值有两条路径，优先级从上到下：
  1. **文档元素**（ControlType=Document）的 Value = 当前页 URL。全屏 / F11 / PWA 窗口下
     工具栏被隐藏、地址栏控件不存在，但文档始终在，故这条是主路径；且文档的 Value 永远是
     已打开的页面地址，不可能是用户正在输入的半截文本。
  2. **地址栏**（几何校验通过的 Edit）兜底，用于文档元素取不到的场景。

隐私硬约束（最高优先级）：
  - 完整 URL 只允许存在于 worker 线程「读值 → extract_domain」这一段调用栈内；
  - 绝不存成成员变量、绝不进任何日志（含 debug 级）、绝不跨线程传递原始 URL；
  - 共享状态只保存已剥离的 domain + hwnd + 采样时间戳。

**读取属性白名单**（改动本文件时必须同步维护这份清单，只减不增）：
  ControlType / IsValuePatternAvailable  —— 仅作为查找条件，不取值
  BoundingRectangle                      —— 地址栏几何校验
  IsOffscreen                            —— 过滤后台标签页的文档
  HasKeyboardFocus                       —— 判断用户是否正在地址栏输入
  Value                                  —— 唯一取值项，出栈即只剩 domain
清单之外的一律不读。**尤其绝不读 Name**（那是页面标题/窗口标题，比域名敏感得多）。

跨平台约束：本文件顶层只 import 标准库 + 纯函数 extract_domain（Linux 安全）。
comtypes / ctypes.windll 的一切引用都延迟到 worker 线程内首次使用；进程内其它线程
不碰 COM。非 Windows 环境即使误 import 本模块也不会在 import 期报错。
"""

import ctypes
import threading
import time

from ..utils.url_domain import extract_domain


# ---- UI Automation 常量（数值 + 命名常量注释；worker 内以生成模块 getattr 兜底数值） ----
_UIA_EditControlTypeId = 50004               # UIA_EditControlTypeId
_UIA_ControlTypePropertyId = 30003           # UIA_ControlTypePropertyId
_UIA_IsValuePatternAvailablePropertyId = 30043  # UIA_IsValuePatternAvailablePropertyId
_UIA_ValueValuePropertyId = 30045            # UIA_ValueValuePropertyId
_UIA_HasKeyboardFocusPropertyId = 30008      # UIA_HasKeyboardFocusPropertyId
_UIA_BoundingRectanglePropertyId = 30001     # UIA_BoundingRectanglePropertyId
_UIA_DocumentControlTypeId = 50030           # UIA_DocumentControlTypeId
_UIA_IsOffscreenPropertyId = 30022           # UIA_IsOffscreenPropertyId
_TreeScope_Descendants = 4                   # TreeScope_Descendants

# COINIT_MULTITHREADED = 0x0
_COINIT_MULTITHREADED = 0x0

# 采样节流参数
_SAMPLE_INTERVAL_S = 2.0      # active 时每 2s 采样一次
_IDLE_POLL_S = 0.5            # 非 active 时每 0.5s 轮询 flag，零 UIA 调用
_DOWNGRADE_INTERVAL_S = 10.0  # 同一 hwnd 连续失败后降频
_MAX_HWND_FAILS = 3           # 连续 3 次异常/找不到 → 降频

# ---- 地址栏几何校验（隐私护栏，勿删） ----
# 「Edit + 有 Value 模式」这一条件本身并不等于地址栏——页内的搜索框/登录框同样满足，
# 一旦命中就会读到用户正在输入的内容。故再按几何形状校验：地址栏必然贴着窗口顶部且宽而扁，
# 页内输入框位于文档区（远离顶部）。几何校验不依赖本地化 Name，也不依赖各浏览器不稳定的
# AutomationId，跨 Chromium 系/Firefox 通用。
# 阈值都要扛住高 DPI（UIA 与 GetWindowRect 都是物理像素，300% 缩放下所有数值 ×3）：
# 顶边偏移的上限取「固定值」与「控件自身高度的若干倍」的较大者——offset/height 的比值
# 与缩放无关（地址栏 ≈1.5~3 倍行高，页内输入框动辄十几倍），故这条规则天然 DPI 无关。
_ADDR_MAX_TOP_OFFSET = 160.0   # 顶边偏移上限（100% 缩放下的固定兜底）
_ADDR_MAX_TOP_ROWS = 5.0       # 顶边偏移上限的另一半：控件高度的倍数（高 DPI 下由它接管）
_ADDR_MIN_TOP_OFFSET = -40.0   # 下界：排除窗口之外的浮动元素
_ADDR_MIN_WIDTH = 120.0        # 地址栏最小宽度（排除小输入框；高 DPI 只会更宽，不会误杀）
_ADDR_MAX_HEIGHT = 140.0       # 地址栏最大高度（排除多行文本域；300% 缩放下地址栏约 96px）
_ADDR_MAX_CANDIDATES = 8       # 最多校验前 N 个候选，避免深树遍历开销

# ---- 文档元素（主路径）----
_DOC_MAX_CANDIDATES = 8        # 同上，只看前 N 个 Document 候选
# 文档元素缓存存活上限：定期重找，防"元素已脱离却仍返回旧 URL"。
# 正常导航会销毁旧元素、读值直接抛异常（那条路径已即时作废缓存），这里只是兜底，
# 故取值偏大——重找要 FindAll 走一遍子树，大页面上开销不小，不宜频繁。
_DOC_CACHE_TTL_S = 120.0
# 文档元素**找不到**时的负缓存：这段时间内不再全树扫描，直接交给地址栏兜底。
# 没有这条的话，"有地址栏但没有文档元素"的窗口（如渲染进程无障碍未就绪）会因为地址栏
# 采成功、失败计数被清零、永不降频 → 每 2s 白扫一遍整棵子树。
_DOC_RETRY_AFTER_S = 30.0
# 地址栏缓存元素连续空读多少次后作废重找。元素脱离通常会抛 E_ELEMENTNOTAVAILABLE
# （那条路径已即时作废），但也可能只是静默返回空串——没有这条就会永久哑掉。
_EDIT_MAX_EMPTY_READS = 5


class _RECT(ctypes.Structure):
    """Win32 RECT（GetWindowRect 用）。ctypes 是标准库，Linux 下定义结构体同样安全。"""

    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _const(mod, name: str, default: int) -> int:
    try:
        return int(getattr(mod, name, default))
    except Exception:
        return int(default)


class BrowserUrlWatcher:
    """在独立 daemon 线程内用 UIA 采集前台浏览器当前页 domain（文档元素优先，地址栏兜底）。

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
        self._cache_doc = None    # 文档元素（主路径），按 hwnd 缓存 + TTL 重找
        self._doc_ts = 0.0        # 文档元素缓存建立时刻（monotonic）
        self._doc_miss_ts = 0.0   # 最近一次「找不到文档元素」时刻（负缓存，0=无）
        self._edit_empty_reads = 0  # 地址栏缓存元素连续空读次数（自愈用）
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
                "bounds_prop": _const(mod, "UIA_BoundingRectanglePropertyId", _UIA_BoundingRectanglePropertyId),
                "doc_type": _const(mod, "UIA_DocumentControlTypeId", _UIA_DocumentControlTypeId),
                "offscreen_prop": _const(mod, "UIA_IsOffscreenPropertyId", _UIA_IsOffscreenPropertyId),
                "scope_desc": _const(mod, "TreeScope_Descendants", _TreeScope_Descendants),
            }
            return uia, consts
        except Exception as e:
            # 创建阶段无任何 URL，记 repr 便于定位（如 RPC_E_CHANGED_MODE / gen 缓存写失败）
            self._debug("browser_url worker: UIA 创建失败 %s: %r", type(e).__name__, e)
            return None, None

    def _sample_once(self, user32, uia, consts) -> None:
        """采一次：先文档元素，取不到再退回地址栏。

        两个读取器统一返回 `(ok, domain)`：
          - `ok=False` = 硬失败（元素找不到 / COM 异常）→ 计入失败降频；
          - `ok=True, domain=""` = 读到了但不是可记录的 http(s) 页面（内部页），不算失败；
          - `ok=True, domain="x.com"` = 成功。
        两条路都硬失败才降频——避免"读到空串也被当成功"导致失败计数永远清零、探针哑掉。
        """
        hwnd = int(user32.GetForegroundWindow() or 0)
        if not hwnd:
            return

        # hwnd 变化：重置缓存（文档/Edit 元素 + 失败计数），换 hwnd 重置降频
        if hwnd != self._cache_hwnd:
            self._cache_hwnd = hwnd
            self._cache_edit = None
            self._cache_doc = None
            self._doc_ts = 0.0
            self._doc_miss_ts = 0.0  # 换窗口立刻重试一次文档元素，不继承上个窗口的负缓存
            self._edit_empty_reads = 0
            self._hwnd_fail = 0

        ok, dom = self._read_document_domain(uia, consts, hwnd)
        if not dom:
            ok_bar, dom_bar = self._read_address_bar_domain(uia, consts, hwnd, user32)
            ok = ok or ok_bar
            dom = dom or dom_bar

        if not ok:
            self._note_failure()
            return

        self._hwnd_fail = 0
        if dom:
            with self._state_lock:
                self._domain = dom
                self._hwnd = hwnd
                self._ts = time.monotonic()
        # dom 为空（内部页 / 搜索词）：不更新，旧值自然过期即可

    def _read_document_domain(self, uia, consts, hwnd):
        """主路径：读文档元素的 Value（= 当前页 URL），立即剥成 domain。返回 (ok, domain)。

        全屏 / F11 / PWA 窗口下地址栏控件不存在，但文档元素仍在 → 这条路照样采得到。
        隐私：只读 Value 一项；完整 URL 只在本函数栈内存在，出栈即只剩 domain。
        """
        doc = self._cache_doc
        if doc is not None and (time.monotonic() - self._doc_ts) > _DOC_CACHE_TTL_S:
            # TTL 到期强制重找，防元素已脱离却仍返回旧 URL（同时丢掉对旧元素的引用）
            self._cache_doc = None
            doc = None
        if doc is None:
            now = time.monotonic()
            if self._doc_miss_ts and (now - self._doc_miss_ts) < _DOC_RETRY_AFTER_S:
                return False, ""  # 负缓存期内不再全树扫描，本拍直接交给地址栏兜底
            doc = self._find_document(uia, consts, hwnd)
            if doc is None:
                self._doc_miss_ts = now
                return False, ""
            self._doc_miss_ts = 0.0
            self._cache_doc = doc
            self._doc_ts = now

        try:
            raw = doc.GetCurrentPropertyValue(consts["value_value_prop"])
        except Exception as e:
            # 跨文档导航会销毁旧文档元素 → 作废缓存，下一拍重找
            self._cache_doc = None
            self._debug("browser_url worker: doc 读值失败 hwnd=%s err=%s",
                        self._cache_hwnd, type(e).__name__)
            return False, ""

        # 完整 URL 只在此处栈内存在，立即抽取 domain，绝不落成员/日志
        raw_str = raw if isinstance(raw, str) else ""
        dom = extract_domain(raw_str)
        del raw, raw_str  # 尽早释放对原始 URL 的引用
        return True, dom

    def _find_document(self, uia, consts, hwnd):
        """定位当前标签页的文档元素（ControlType=Document 且有 Value 模式）。

        取树序第一个「非 offscreen」的候选：
          - 树序是 pre-order，外层文档排在内嵌 iframe 之前 → 不会把广告 iframe 的域名当成站点；
          - IsOffscreen 过滤掉后台标签页残留的文档（Firefox 会把它们留在树里）。
        """
        root = uia.ElementFromHandle(hwnd)
        if not root:
            return None
        cond_type = uia.CreatePropertyCondition(
            consts["ctrl_type_prop"], consts["doc_type"]
        )
        cond_val = uia.CreatePropertyCondition(
            consts["is_value_avail_prop"], True
        )
        cond = uia.CreateAndCondition(cond_type, cond_val)
        found = root.FindAll(consts["scope_desc"], cond)
        if not found:
            return None
        try:
            count = int(found.Length)
        except Exception:
            return None
        for i in range(min(count, _DOC_MAX_CANDIDATES)):
            try:
                el = found.GetElement(i)
                if el is None:
                    continue
                if bool(el.GetCurrentPropertyValue(consts["offscreen_prop"])):
                    continue
            except Exception:
                continue
            return el
        return None

    def _read_address_bar_domain(self, uia, consts, hwnd, user32):
        """兜底路径：读地址栏（几何校验通过的那一个）。返回 (ok, domain)。

        地址栏有键盘焦点 = 用户正在输入 → 主动跳过，返回 (True, "")（不算失败、不降频），
        避免把没输完的搜索词当成网址。
        """
        edit = self._cache_edit
        if edit is None:
            edit = self._find_edit(uia, consts, hwnd, user32)
            if edit is None:
                return False, ""
            self._cache_edit = edit

        try:
            focused = edit.GetCurrentPropertyValue(consts["has_focus_prop"])
        except Exception as e:
            self._cache_edit = None
            self._debug("browser_url worker: 地址栏读焦点失败 hwnd=%s err=%s",
                        self._cache_hwnd, type(e).__name__)
            return False, ""
        if focused:
            return True, ""

        try:
            raw = edit.GetCurrentPropertyValue(consts["value_value_prop"])
        except Exception as e:
            self._cache_edit = None
            self._debug("browser_url worker: 地址栏读值失败 hwnd=%s err=%s",
                        self._cache_hwnd, type(e).__name__)
            return False, ""

        # 完整 URL 只在此处栈内存在，立即抽取 domain，绝不落成员/日志
        raw_str = raw if isinstance(raw, str) else ""
        dom = extract_domain(raw_str)
        del raw, raw_str  # 尽早释放对原始 URL 的引用

        # 自愈：连续空读到阈值就作废缓存元素重找（它可能已脱离但只是静默返回空串）
        if dom:
            self._edit_empty_reads = 0
        else:
            self._edit_empty_reads += 1
            if self._edit_empty_reads >= _EDIT_MAX_EMPTY_READS:
                self._edit_empty_reads = 0
                self._cache_edit = None
        return True, dom

    def _find_edit(self, uia, consts, hwnd, user32):
        """在窗口子树里定位**地址栏** Edit 控件（通不过几何校验的一律不要）。

        用 FindAll 而非 FindFirst：树里第一个 Edit 未必是地址栏（页内搜索框/登录框
        也满足「Edit + 有 Value 模式」），逐个按 `_is_address_bar` 校验取第一个通过的。
        一个都不通过 → 返回 None（宁可这一拍不采，也不去读页内输入框）。
        """
        root = uia.ElementFromHandle(hwnd)
        if not root:
            return None
        win_rect = self._window_rect(user32, hwnd)
        if win_rect is None:
            return None
        cond_type = uia.CreatePropertyCondition(
            consts["ctrl_type_prop"], consts["edit_type"]
        )
        cond_val = uia.CreatePropertyCondition(
            consts["is_value_avail_prop"], True
        )
        cond = uia.CreateAndCondition(cond_type, cond_val)
        found = root.FindAll(consts["scope_desc"], cond)
        if not found:
            return None
        try:
            count = int(found.Length)
        except Exception:
            return None
        for i in range(min(count, _ADDR_MAX_CANDIDATES)):
            try:
                el = found.GetElement(i)
            except Exception:
                continue
            if el is None:
                continue
            if self._is_address_bar(el, consts, win_rect):
                return el
        return None

    def _window_rect(self, user32, hwnd):
        """窗口包围盒 → (left, top, right, bottom)，失败返回 None。"""
        try:
            r = _RECT()
            if not user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(r)):
                return None
            return (float(r.left), float(r.top), float(r.right), float(r.bottom))
        except Exception:
            return None

    def _element_rect(self, el, consts):
        """元素包围盒 → (left, top, right, bottom)，失败返回 None。

        优先 `CurrentBoundingRectangle`（RECT 结构，语义明确）；不可用时退回
        `GetCurrentPropertyValue`（VARIANT 内是 [left, top, width, height] 四个 double）。
        """
        try:
            r = el.CurrentBoundingRectangle
            return (float(r.left), float(r.top), float(r.right), float(r.bottom))
        except Exception:
            pass
        try:
            v = el.GetCurrentPropertyValue(consts["bounds_prop"])
            if v is None or len(v) < 4:
                return None
            left, top, width, height = float(v[0]), float(v[1]), float(v[2]), float(v[3])
            return (left, top, left + width, top + height)
        except Exception:
            return None

    def _is_address_bar(self, el, consts, win_rect) -> bool:
        """几何校验：该 Edit 是否为地址栏（贴窗口顶部 + 宽而扁）。

        隐私护栏——不通过即视为页内输入框，绝不读它的值。取不到包围盒同样判否
        （读不到位置 = 无法证明它是地址栏）。
        """
        rect = self._element_rect(el, consts)
        if rect is None or win_rect is None:
            return False
        left, top, right, bottom = rect
        width, height = right - left, bottom - top
        if width < _ADDR_MIN_WIDTH or height <= 0 or height > _ADDR_MAX_HEIGHT:
            return False
        top_offset = top - win_rect[1]
        # 上限取固定值与「若干倍控件高度」的较大者：后者随 DPI 一起放大，
        # 避免 200%/300% 缩放 + Firefox 多层工具栏时把真地址栏误杀。
        max_offset = max(_ADDR_MAX_TOP_OFFSET, height * _ADDR_MAX_TOP_ROWS)
        return _ADDR_MIN_TOP_OFFSET <= top_offset <= max_offset

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

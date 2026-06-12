"""
Constants for bootstrap: paths and ports.
"""
import sys
from pathlib import Path

# ----------------------------
# 基本常量（打包成 exe 时：资源在 exe 同目录，数据目录在 exe 同级 user_data 文件夹）
# ----------------------------
if getattr(sys, "frozen", False):
    # 打包后：资源和 exe 在同一目录
    # 目录结构: dist\EyE Care\EyeE Care.exe + eye_care\ + docs\ + user_data\
    PROJECT_ROOT = Path(sys.executable).resolve().parent
    _BUNDLE_ROOT = PROJECT_ROOT  # 资源就在根目录，不在 _MEIPASS
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    _BUNDLE_ROOT = PROJECT_ROOT

UI_WEB_DIR = _BUNDLE_ROOT / "eye_care" / "ui" / "web"
UI_INDEX_PATH = UI_WEB_DIR / "index.html"

# 默认端口：本地 API 使用 17993
DEFAULT_API_PORT = 17993

HEALTH_POLL_MS = 50  # 从300ms降到50ms，更快响应
HEALTH_TIMEOUT_MS = 3000  # 从15秒降到3秒，Flask启动通常<1秒

# 拖拽区域注入：默认关闭(UI 已在 HTML/CSS 标注)
ENABLE_DRAG_REGION_INJECT = False

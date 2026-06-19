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

# 声音等静态资源目录（QML 迁移后，原 ui/web 已退役，资源迁至 eye_care/assets）
ASSETS_DIR = _BUNDLE_ROOT / "eye_care" / "assets"

# 默认端口：保留常量供 main.py 的 --no-ui --api-port 头less 模式参考（GUI 已不再用 Flask）
DEFAULT_API_PORT = 17993

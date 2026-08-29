# -*- mode: python ; coding: utf-8 -*-

import os

# 获取项目根目录
project_root = os.path.dirname(os.path.abspath(SPEC))

# 注意：不打包 user_data 目录，user_data 目录在运行时动态创建
a = Analysis(
    ['main.py'],
    pathex=[project_root],
    binaries=[],
    datas=[
        # 仅打包运行期按路径加载的资源（QML 源 + 声音）。Python 代码本身已编译进 PYZ，
        # 无需再以源码形式整目录拷贝（旧 ('eye_care','eye_care') 会连 .py 源 + __pycache__ 一起带进来）。
        # qml 同时供 _internal(__file__ 相对，notify/rest 浮层) 与外层(PROJECT_ROOT, AppShell) 加载；
        # 外层副本由 build_exe.bat 的 xcopy 从 _internal 复制。
        ('eye_care/qt_quick/qml', 'eye_care/qt_quick/qml'),
        ('eye_care/assets', 'eye_care/assets'),
        # 诊断事件字典：策略引擎运行期按路径读取（policy_engine._find_event_codes_path）。
        ('eye_care/diagnostics/event_codes.yml', 'eye_care/diagnostics'),
        ('icon.ico', '.'),
        ('icon.png', '.'),
        ('README.md', '.'),
        # Note: version_info.txt is a build-time input (EXE version= below), not a runtime asset.
        # Note: user manual (Chinese filename) is excluded to avoid encoding issues on non-CJK build hosts.
    ],
    hiddenimports=[
        'yaml',          # PyYAML -- imported inside function body, may not be auto-detected
        'PIL',
        'PIL.Image',
        'PySide6',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        # QML/Qt Quick 原生外壳（已彻底取代 QWebEngine/web SPA）。这些 hiddenimports 触发
        # PySide6 的 PyInstaller 钩子收集 QtQuick/QtQml 运行时插件与 qml 模块——含
        # QtQuick.Controls.Basic（强制 Basic 样式才吃自定义滚动条）、QtQuick.Shapes（饼图）、
        # QtQuick.Effects 的 MultiEffect（选中 tab/卡片投影）。插件本体随 PySide6 wheel 提供。
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuickControls2',
        'PySide6.QtNetwork',       # QLocalServer/QLocalSocket 单实例检测
        # eye_care 主入口 + 全部桥（多在函数内延迟 import；显式列出确保被收进 PYZ）。
        'eye_care.qt',
        'eye_care.qt.runtime_shell',
        'eye_care.qt_quick',
        'eye_care.qt_quick.shell_integration',
        'eye_care.qt_quick.dashboard_data',
        'eye_care.qt_quick.left_panel_bridge',
        'eye_care.qt_quick.right_panel_bridge',
        'eye_care.qt_quick.settings_bridge',
        'eye_care.qt_quick.blacklist_bridge',
        'eye_care.qt_quick.apps_bridge',
        'eye_care.qt_quick.sites_bridge',
        'eye_care.qt_quick.update_bridge',
        'eye_care.update_service',
        'eye_care.qt_quick.calendar_bridge',
        'eye_care.qt_quick.notify_overlay',
        'eye_care.qt_quick.rest_overlay',
        # 浏览器 domain 统计（2026-07）：UIA 探针 + favicon 服务（函数内延迟 import，显式收进 PYZ）。
        # comtypes 由 pyinstaller-hooks-contrib 的钩子处理 frozen 下的 comtypes.gen 接口缓存。
        'comtypes',
        'comtypes.client',
        'eye_care.probes.browser_url',
        'eye_care.probes.win_browser_url',
        # 会话可交互性探针：win_session 在 session.py 函数内延迟导入，显式列出避免
        # 冻结包漏收后把探针失败误判成不可交互、导致发布版停止计时。
        'eye_care.probes.session',
        'eye_care.probes.win_session',
        'eye_care.services.favicon_service',
        # 站点归并规则（展示层）：仅函数内延迟 import（snapshot_service/api.common/sites_bridge），显式收进 PYZ。
        'eye_care.utils.site_rules',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# Independent one-file updater. The running app is copied to user_data/updates/runtime
# before launch, so it can replace the entire one-dir application after the main PID exits.
updater_a = Analysis(
    ['updater_main.py'],
    pathex=[project_root],
    binaries=[],
    datas=[],
    hiddenimports=['eye_care.update_helper'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6', 'PIL', 'yaml', 'psutil', 'win32api', 'comtypes'],
    noarchive=False,
    optimize=0,
)
updater_pyz = PYZ(updater_a.pure)

updater_exe = EXE(
    updater_pyz,
    updater_a.scripts,
    updater_a.binaries,
    updater_a.datas,
    [],
    name='EyE Care Updater',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=['icon.ico'],
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EyE Care',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
    icon=['icon.ico'],
)

coll = COLLECT(
    exe,
    updater_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='EyE Care',
)

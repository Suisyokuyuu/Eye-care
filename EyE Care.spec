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
        ('eye_care', 'eye_care'),
        ('docs', 'docs'),
        ('icon.ico', '.'),
        ('icon.png', '.'),
        ('requirements.txt', '.'),
        ('README.md', '.'),
        ('version_info.txt', '.'),
    ],
    hiddenimports=[
        'webview',
        'PIL',
        'PIL.Image',
        'eye_care.qt',
        'eye_care.qt.runtime_shell',
        'PySide6',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebChannel',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

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
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='EyE Care',
)

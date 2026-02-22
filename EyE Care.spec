# -*- mode: python ; coding: utf-8 -*-

import os

# 获取项目根目录
project_root = os.path.dirname(os.path.abspath(SPEC))

# 注意：不打包 user_data 目录！user_data 目录在运行时动态创建
a = Analysis(
    ['main.py'],
    pathex=[project_root],
    binaries=[],
    datas=[
        # eye_care 包
        ('eye_care', 'eye_care'),
        # docs 文档
        ('docs', 'docs'),
        # 图标
        ('icon.ico', '.'),
        ('icon.png', '.'),
        # 配置文件（打包后放到外层）
        ('requirements.txt', '.'),
        ('README.md', '.'),
        ('version_info.txt', '.'),
    ],
    hiddenimports=[
        'webview',
        'pywebview',
        'PIL',
        'PIL.Image',
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

# 打包后处理：将资源文件从 _internal 复制到外层
# 具体操作在 build_exe.bat 中完成：
# 1. 复制 eye_care\docs\icon.* 到外层
# 2. 创建 user_data 目录

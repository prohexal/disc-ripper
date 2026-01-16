# -*- mode: python ; coding: utf-8 -*-

project_dir = "/Users/jpdavids/codeRepo/disc-ripper"
icon_path = "/Users/jpdavids/codeRepo/disc-ripper/DiscRipper.icns"

a = Analysis(
    ['disc_ripper.py'],
    pathex=[project_dir],
    binaries=[],
    datas=[(icon_path, ".")],
    hiddenimports=['keyring'],
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
    name='DiscRipper',
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
    icon=[icon_path],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DiscRipper',
)
app = BUNDLE(
    coll,
    name='DiscRipper.app',
    icon=icon_path,
    bundle_identifier='com.discripper.app',
)

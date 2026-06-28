# -*- mode: python ; coding: utf-8 -*-
"""Canonical PyInstaller spec — the single source of truth for the build.

Both build_exe.py (normal build) and build_for_customer.py (PyArmor-hardened
build) invoke this spec, so the bundled data, hidden imports, collected packages,
and icon stay consistent across both paths.
"""

from PyInstaller.utils.hooks import collect_all

datas = [('assets', 'assets'), ('Resource', 'Resource')]
binaries = []
hiddenimports = ['soundfile', 'faster_whisper']

# Pull in everything (data files, native libs, submodules) for the heavy
# native packages, mirroring the previous --collect-all flags.
for _pkg in ('onnxruntime', 'faster_whisper', 'ctranslate2', 'tokenizers'):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Defense in depth: app.py never imports these vendor-only signing/admin
    # modules, so PyInstaller's analysis already drops them. Exclude them
    # explicitly so a stray future import can never leak the keygen toolchain
    # into a customer build. (license_codec / license_guard ARE shipped.)
    excludes=[
        'licensing_core',
        'license_manager_app',
        'license_manager_window',
        'admin_keygen',
        'setup_security',
        'generate_test_license',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FasterWhisperGUI',
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
    icon='Resource/Icon/faster-whisper-icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FasterWhisperGUI',
)

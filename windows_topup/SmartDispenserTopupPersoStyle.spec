# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app_perso_style.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('schema.sql', '.'),
        (r'C:\Users\MSI\AppData\Local\Programs\Python\Python312\tcl\tcl8.6', r'tcl\tcl8.6'),
        (r'C:\Users\MSI\AppData\Local\Programs\Python\Python312\tcl\tk8.6', r'tcl\tk8.6'),
    ],
    hiddenimports=['mysql.connector', 'serial'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['tk_runtime_hook.py'],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SmartDispenserTopupPersoStyle',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for PeygiriPanel.exe — build: pyinstaller PeygiriPanel.spec
# One file, no console. config.ini, peygiri_panel.db, backups\ and logs\ are
# created next to the exe on first run (src/config/settings.py: base_dir).

hiddenimports = ['_cffi_backend']   # bcrypt

a = Analysis(
    ['start.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('src\\templates', 'src\\templates'),
        ('src\\static', 'src\\static'),
        ('src\\adapters\\sqlite\\schema.sql', 'src\\adapters\\sqlite'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'tkinter'],
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
    name='PeygiriPanel',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

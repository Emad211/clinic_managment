# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


root = Path(SPECPATH)
src = root / "src"

datas = [
    (str(src / "templates"), "src/templates"),
    (str(src / "static"), "src/static"),
    (str(src / "adapters" / "sqlite" / "schema.sql"), "src/adapters/sqlite"),
    (
        str(src / "domain" / "clinical_engine" / "schemas"),
        "src/domain/clinical_engine/schemas",
    ),
    (
        str(src / "domain" / "clinical_engine" / "rule_artifacts"),
        "src/domain/clinical_engine/rule_artifacts",
    ),
]
hiddenimports = sorted(
    set(
        [
            "jsonschema",
            "segno",
            "segno.helpers",
        ]
        + collect_submodules("waitress")
    )
)

analysis = Analysis(
    ["start.py"],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="SpecialistClinic",
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

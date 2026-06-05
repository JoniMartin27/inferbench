# -*- mode: python ; coding: utf-8 -*-
# Empaqueta el backend FastAPI como un único ejecutable que Electron lanza como sidecar.
#
# Uso:
#   uv pip install pyinstaller
#   pyinstaller backend/pyinstaller.spec --clean --noconfirm
#
# El binario resultante (dist/inferbench-backend[.exe]) se copia a
# frontend/electron/sidecar/ y electron-builder lo embebe en el instalador.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

ROOT = Path(SPECPATH).resolve()

# Incluye el .dist-info del paquete para que importlib.metadata.version() resuelva la
# versión en el bundle (si no, main.py caería al fallback "0.0.0+dev").
_pkg_metadata = copy_metadata("inferbench-backend")

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        ("data/models.json", "data"),
        ("data/prompts.json", "data"),
        *_pkg_metadata,
    ],
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "pynvml",
        "docker",
        "sse_starlette",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="inferbench-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False if sys.platform == "darwin" else True,
    disable_windowed_traceback=False,
    icon=None,
)

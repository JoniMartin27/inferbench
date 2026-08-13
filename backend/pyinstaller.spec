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
    # TODO el contenido de data/ MENOS la base de datos.
    #
    # Antes se listaban models.json y prompts.json a mano, y se quedaban fuera los assets
    # que referencia el propio prompts.json: `vision_scene.png`, `vision_count.png` y
    # `context_haystack.txt`. Medido en el exe instalado — su bundle solo traía los dos
    # JSON — así que **3 de los 7 prompts estaban rotos en la app empaquetada**:
    # `vision-scene`, `vision-count` y `long-context` no encontraban su fichero.
    # Enumerar a mano se rompe en cuanto alguien añade un prompt con asset nuevo; hay un
    # test (`tests/test_datos_empaquetados.py`) que ata el spec a lo que pide prompts.json.
    #
    # El .sqlite NO se empaqueta: es la base de datos de desarrollo y además, congelado,
    # la app usa la de %APPDATA% (ver `db._db_path`). Meterla aquí distribuiría runs de
    # pruebas a todo el que instale.
    datas=[
        *[
            (str(p), "data")
            for p in sorted((ROOT / "data").iterdir())
            if p.is_file() and p.suffix != ".sqlite"
        ],
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

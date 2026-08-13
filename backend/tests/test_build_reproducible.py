"""El binario que se distribuye debe construirse con lo que CI valida.

Hay tres caminos que producen el sidecar (el script de Windows, el de Unix y el
workflow de release) y los tres deben instalar igual. Dos cosas se han escapado ya:

1. `uv pip install -e . pyinstaller` ignora uv.lock y resuelve libre, así que el
   binario publicado llevaba dependencias que nadie había probado mientras CI
   validaba otras. Mismo patrón que tumbó el gate con ruff 0.16 y dejó Serve/MCP
   roto con mcp 2.0.
2. `uv sync` sin `--python` coge el intérprete más nuevo instalado en la máquina.
   Al migrar los scripts al lock, la primera versión construyó el sidecar con
   CPython 3.14 en vez del 3.11 que fija el proyecto: mismo lock, runtime distinto.

Ninguno de los dos rompe nada visible en el momento; se descubren cuando el
usuario abre el instalador. De ahí este contrato.
"""

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]

CAMINOS_DE_BUILD = [
    RAIZ / "scripts" / "build-sidecar.ps1",
    RAIZ / "scripts" / "build-sidecar.sh",
    RAIZ / ".github" / "workflows" / "release.yml",
]

PYTHON_DEL_PROYECTO = "3.11"


def _ordenes(camino: Path) -> str:
    """Las órdenes que se ejecutan de verdad, en una sola línea comparable.

    Se quitan los comentarios (los tres formatos usan `#`) porque explican
    precisamente lo que NO hay que hacer y dispararían los asertos en falso. Y se
    quitan comillas, comas y paréntesis porque PowerShell pasa los argumentos como
    lista —`@("sync", "--locked", ...)`— y la misma orden se escribe distinta en
    cada fichero.
    """
    lineas = [linea.split("#", 1)[0] for linea in camino.read_text(encoding="utf-8").splitlines()]
    plano = re.sub(r"[\"',()@]", " ", "\n".join(lineas))
    return re.sub(r"\s+", " ", plano)


@pytest.mark.parametrize("camino", CAMINOS_DE_BUILD, ids=lambda p: p.name)
def test_el_camino_existe(camino: Path):
    assert camino.is_file(), f"falta {camino.relative_to(RAIZ)}"


@pytest.mark.parametrize("camino", CAMINOS_DE_BUILD, ids=lambda p: p.name)
def test_instala_desde_el_lock(camino: Path):
    plano = _ordenes(camino)

    assert "uv sync" in plano, "el build debe usar `uv sync` (no `uv pip install`)"
    assert "uv sync --locked" in plano, (
        "falta `--locked`: sin él uv puede reescribir el lock en silencio y el "
        "binario sale con versiones que nadie ha validado"
    )
    assert "uv pip install" not in plano, (
        "`uv pip install` ignora uv.lock: resuelve libre y desalinea el binario "
        "distribuido de lo que valida CI"
    )


@pytest.mark.parametrize("camino", CAMINOS_DE_BUILD, ids=lambda p: p.name)
def test_fija_el_interprete(camino: Path):
    plano = _ordenes(camino)

    assert f"--python {PYTHON_DEL_PROYECTO}" in plano, (
        f"falta `--python {PYTHON_DEL_PROYECTO}`: uv elegiría el intérprete más "
        "nuevo de la máquina y el sidecar saldría con otro runtime"
    )


@pytest.mark.parametrize("camino", CAMINOS_DE_BUILD, ids=lambda p: p.name)
def test_lanza_pyinstaller_dentro_del_entorno(camino: Path):
    plano = _ordenes(camino)

    assert "uv run pyinstaller" in plano, (
        "PyInstaller debe ejecutarse con `uv run` para que use la venv del lock; "
        "un `pyinstaller` suelto puede resolverse al del PATH del sistema"
    )


def test_pyinstaller_esta_declarado_con_techo():
    """Si PyInstaller no está en pyproject, no está en el lock y vuelve a resolverse libre."""
    pyproject = (RAIZ / "backend" / "pyproject.toml").read_text(encoding="utf-8")

    assert "build = [" in pyproject, "falta el extra `build` con las herramientas de empaquetado"
    build = pyproject.split("build = [", 1)[1].split("]", 1)[0]
    assert "pyinstaller" in build, "el extra `build` debe declarar pyinstaller"
    assert "<7" in build, (
        "pyinstaller sin techo de mayor: una 7.x puede cambiar el empaquetado y "
        "romper el binario sin que nadie toque el proyecto"
    )


def test_el_release_pasa_los_tests_antes_de_empaquetar():
    """Empaquetar sin correr la suite publica fallos que CI habría cazado."""
    workflow = (RAIZ / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "pytest" in workflow, "el release debe correr la suite antes de construir el binario"
    pos_tests = workflow.index("pytest")
    pos_build = workflow.index("uv run pyinstaller")
    assert pos_tests < pos_build, "los tests deben ir ANTES de empaquetar, no después"

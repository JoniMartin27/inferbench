"""Todo lo que `prompts.json` referencia tiene que acabar dentro del ejecutable.

El fallo, medido en el exe INSTALADO: `pyinstaller.spec` listaba a mano `models.json` y
`prompts.json`, y se quedaban fuera los assets que el propio `prompts.json` referencia.
El bundle traía literalmente `['models.json', 'prompts.json']`, así que en la app
empaquetada **3 de los 7 prompts estaban rotos** — `vision-scene`, `vision-count` y
`long-context` no encontraban su fichero.

Enumerar a mano se rompe solo: en cuanto alguien añade un prompt con un asset nuevo y no
se acuerda del spec, vuelve el fallo y no se nota hasta que alguien instala la app. Este
test ata las dos cosas.
"""

import json
import pathlib

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parent.parent
_DATA = _BACKEND / "data"
_SPEC = _BACKEND / "pyinstaller.spec"


def _assets_referenciados() -> set[str]:
    """Ficheros de `data/` que los prompts necesitan en tiempo de ejecución."""
    crudo = json.loads((_DATA / "prompts.json").read_text(encoding="utf-8"))
    items = crudo if isinstance(crudo, list) else crudo.get("prompts", crudo)
    referencias = set()
    for p in items:
        for clave in ("image", "context_file"):
            if p.get(clave):
                referencias.add(p[clave])
    return referencias


def test_hay_assets_que_comprobar():
    """Si esto falla, el test de abajo sería vacío y no probaría nada."""
    assert _assets_referenciados(), "prompts.json debería referenciar imágenes/contexto"


@pytest.mark.parametrize("asset", sorted(_assets_referenciados()))
def test_el_asset_existe_en_data(asset):
    assert (_DATA / asset).is_file(), f"prompts.json referencia {asset} y no está en data/"


def test_el_spec_empaqueta_todo_data_menos_la_base_de_datos():
    """El spec no debe volver a enumerar ficheros a mano.

    Se comprueba sobre el fuente porque el `.spec` solo se puede ejecutar dentro de
    PyInstaller (usa `SPECPATH`, `Analysis`, `EXE`… inyectados por él).
    """
    spec = _SPEC.read_text(encoding="utf-8")

    assert '(ROOT / "data").iterdir()' in spec, (
        "el spec debe recorrer data/ entera; enumerar ficheros a mano dejó fuera las "
        "imágenes de visión y el contexto largo"
    )
    assert '.suffix != ".sqlite"' in spec, (
        "la base de datos NO debe empaquetarse: es la de desarrollo, y congelado se usa "
        "la de %APPDATA%"
    )
    for asset in _assets_referenciados():
        assert (
            f'"{asset}"' not in spec
        ), f"{asset} aparece a mano en el spec: eso es justo el patrón que falló"


def test_los_metadatos_del_paquete_siguen_empaquetados():
    """`copy_metadata` es lo que hace que `importlib.metadata.version()` funcione congelado.

    De ahí salen la versión de `/api/health` y la que anuncia el handshake MCP; si se cae
    del spec, la app pasa a decir `0.0.0+dev`.
    """
    spec = _SPEC.read_text(encoding="utf-8")
    assert "copy_metadata(" in spec
    assert "*_pkg_metadata," in spec, "los metadatos deben seguir dentro de `datas`"


def test_la_base_de_datos_de_desarrollo_no_se_distribuye():
    """Empaquetarla enviaría runs de prueba a todo el que instale la app."""
    spec = _SPEC.read_text(encoding="utf-8")
    assert "inferbench.sqlite" not in spec

"""Dónde se guarda el SQLite según se ejecute desde el código o empaquetado.

El fallo que fijan, medido en la app INSTALADA: `DB_PATH` salía de
`Path(__file__).parent`, y en un onefile de PyInstaller eso cae dentro de
`%TEMP%\\_MEI<aleatorio>\\`, que se crea nuevo en cada arranque y se borra al salir.
Consecuencia: el Historial aparecía **vacío en cada apertura**, todo lo benchmarkeado se
perdía al cerrar la app, y quedaba un `.sqlite` huérfano por lanzamiento en el temporal
(se encontraron cuatro). Comparar runs y exportar a CSV/JSON —la razón de ser de esa
pestaña— no servían de nada en el build empaquetado.

Pasó desapercibido mucho tiempo porque en las verificaciones la app **reutilizaba un
backend de desarrollo** (que sí escribe en `backend/data/`), así que se veía historial de
verdad y parecía que todo iba bien.

NOTA DE ARNÉS: estos tests llaman a `_db_path()` directamente. NO recargues el módulo `db`
con `importlib.reload` para probar la constante: SQLModel registra las tablas al importar
y el segundo import revienta con "Table 'benchmark_runs' is already defined".
"""

import pathlib
import sys

import db as db_mod


def _ruta(monkeypatch, *, frozen: bool, appdata=None, home=None):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    if appdata is None:
        monkeypatch.delenv("APPDATA", raising=False)
    else:
        monkeypatch.setenv("APPDATA", str(appdata))
    if home is not None:
        monkeypatch.setattr(db_mod.Path, "home", staticmethod(lambda: home))
    return db_mod._db_path()


def test_empaquetado_guarda_en_los_datos_del_usuario(monkeypatch, tmp_path):
    """Lo que arregla el fallo: congelado NO puede escribir junto al ejecutable."""
    appdata = tmp_path / "Roaming"
    appdata.mkdir()

    ruta = _ruta(monkeypatch, frozen=True, appdata=appdata)

    assert ruta.parent == appdata / "InferBench"
    assert ruta.name == "inferbench.sqlite"
    assert ruta.parent.exists(), "la carpeta debe crearse, no solo calcularse"


def test_empaquetado_nunca_escribe_en_el_temporal_de_pyinstaller(monkeypatch, tmp_path):
    """La regresión concreta: `_MEIxxxx` es distinto en cada arranque y se borra al salir."""
    appdata = tmp_path / "Roaming"
    appdata.mkdir()

    ruta = _ruta(monkeypatch, frozen=True, appdata=appdata)

    partes = [p.lower() for p in ruta.parts]
    assert not any(
        p.startswith("_mei") for p in partes
    ), f"la BD caería en el temporal de PyInstaller y se perdería al cerrar: {ruta}"


def test_desde_el_codigo_sigue_en_backend_data(monkeypatch):
    """Desarrollo no debe mezclarse con los datos del usuario."""
    ruta = _ruta(monkeypatch, frozen=False, appdata=None)

    assert ruta.parent.name == "data"
    assert ruta.parent.parent.name == "backend"


def test_sin_appdata_cae_a_la_carpeta_del_usuario(monkeypatch, tmp_path):
    """Sin APPDATA (macOS/Linux, o Windows raro) va a ~/.inferbench, como el resto de cachés.

    OJO: NO parchear `os.name` para simular POSIX — `pathlib` lo lee al construir rutas y
    envenena el intérprete entero ("cannot instantiate 'PosixPath' on your system"), que
    además revienta al propio pytest al formatear el fallo. Basta con quitar APPDATA: la
    condición del código es `os.name == "nt" AND "APPDATA" in os.environ`.
    """
    casa = tmp_path / "casa"
    casa.mkdir()

    ruta = _ruta(monkeypatch, frozen=True, appdata=None, home=casa)

    assert ruta.parent == casa / ".inferbench"
    assert ruta.parent.exists()


def test_la_constante_del_modulo_sale_de_la_funcion():
    """Que `DB_PATH` se DERIVE de `_db_path()`, no se calcule a pelo otra vez.

    Es una comprobación estructural sobre el fuente, y es a propósito: comparar
    `DB_PATH == _db_path()` no vale, porque en el proceso de test `sys.frozen` es falso y
    los dos caminos coinciden — un mutante que reintrodujera la ruta a pelo pasaría el
    test tan campante (comprobado). Lo que hay que impedir es justo esa reintroducción.
    """
    fuente = pathlib.Path(db_mod.__file__).read_text(encoding="utf-8")
    assert "DB_PATH = _db_path()" in fuente, (
        "DB_PATH debe salir de _db_path(); calcularla a pelo devuelve el fallo del "
        "temporal de PyInstaller"
    )

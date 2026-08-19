"""Aislamiento del arnés: los tests NO pueden tocar la base de datos real. Nunca.

Por qué existe este fichero (incidente real, 2026-08-13): un `UPDATE` de reconciliación
llegó a correr contra `backend/data/inferbench.sqlite` —la base de datos DEL USUARIO— y
dejó 135 de 137 filas marcadas `interrupted`. 98 de ellas habían terminado perfectamente.
El Historial pasó de verde a ámbar casi entero.

El camino por el que se cuela es sutil y NO se ve leyendo un test:

    client = TestClient(app)      # <- a nivel de módulo, sin fixture ninguna
    with client:                  # <- esto ARRANCA el lifespan de la app...
        ...                       #    ...que llama a init_db() y reconcile_orphan_runs()

`db.DB_PATH` y `db._engine` se calculan **al importar el módulo**. Cualquier fixture que
los parchee llega tarde para lo que corra antes: pytest crea los fixtures de módulo antes
que los de función, y un `TestClient` de módulo se construye antes todavía. Por eso aquí
no se parchea nada a posteriori: se fuerza la ruta **por entorno y antes de importar `db`**,
que es el único momento en el que la decisión aún no se ha tomado.

Además se vigila la base de datos real de punta a punta de la sesión: si un test la toca,
la suite falla y dice exactamente qué filas cambiaron.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

# --- 1. La BD del arnés se fija ANTES de que nadie importe `db` -------------------------
#
# Este `os.environ[...]` es lo primero que pasa en toda la sesión de pytest: conftest.py se
# importa antes de recolectar los módulos de test, así que cuando `db` se importe (lo haga
# quien lo haga, incluido el lifespan de la app) `DB_PATH` ya saldrá de aquí.
_DIR_ARNES = Path(tempfile.mkdtemp(prefix="inferbench-tests-"))
os.environ["INFERBENCH_DB_PATH"] = str(_DIR_ARNES / "arnes.sqlite")

import db as _db  # noqa: E402  (el orden es load-bearing: el entorno va primero)


def _ruta_bd_real() -> Path:
    """La BD de desarrollo del usuario, la que jamás debe tocarse desde un test."""
    return Path(__file__).resolve().parent.parent / "data" / "inferbench.sqlite"


def _huella(ruta: Path) -> tuple[str, dict[str, str]] | None:
    """(md5 del fichero, {run_id: status}) — o None si la BD no existe (CI, clon limpio)."""
    if not ruta.exists():
        return None
    md5 = hashlib.md5(ruta.read_bytes()).hexdigest()
    estados: dict[str, str] = {}
    try:
        con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
        try:
            estados = dict(con.execute("SELECT id, status FROM benchmark_runs"))
        finally:
            con.close()
    except sqlite3.Error:
        pass  # sin tabla todavía: con el md5 vale
    return md5, estados


_HUELLA_INICIAL: tuple[str, dict[str, str]] | None = None


def pytest_sessionstart(session):  # noqa: ARG001
    global _HUELLA_INICIAL
    _HUELLA_INICIAL = _huella(_ruta_bd_real())


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """Red de seguridad de toda la suite: la BD real tiene que salir como entró.

    Va aquí y no en un test porque un test solo comprueba hasta el momento en que corre;
    esto cubre hasta el último test de la sesión, venga de donde venga el daño.
    """
    if _HUELLA_INICIAL is None:
        return
    despues = _huella(_ruta_bd_real())
    if despues is None:
        session.exitstatus = 1
        print("\nARNÉS: la base de datos REAL ha DESAPARECIDO durante la suite.")
        return
    if despues[0] == _HUELLA_INICIAL[0]:
        return

    antes_estados, despues_estados = _HUELLA_INICIAL[1], despues[1]
    cambios = [
        f"    {rid}: {antes_estados[rid]} -> {despues_estados.get(rid, '<BORRADA>')}"
        for rid in antes_estados
        if antes_estados.get(rid) != despues_estados.get(rid)
    ]
    nuevas = set(despues_estados) - set(antes_estados)
    session.exitstatus = 1
    print("\nARNÉS: la suite ha MODIFICADO la base de datos real del usuario.")
    print(f"    fichero: {_ruta_bd_real()}")
    print(f"    md5 {_HUELLA_INICIAL[0]} -> {despues[0]}")
    if cambios:
        print(f"    {len(cambios)} fila(s) cambiaron de estado:")
        print("\n".join(cambios[:20]))
    if nuevas:
        print(f"    {len(nuevas)} fila(s) nuevas: {sorted(nuevas)[:10]}")


# --- 2. Aserción dura por sesión --------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _la_bd_del_arnes_no_es_la_real():
    """Falla la sesión ENTERA si el arnés apunta a la base de datos real.

    Es la comprobación que el incidente no tuvo: aquí no se confía en que las fixtures se
    hayan ordenado bien, se verifica dónde apunta de verdad el módulo `db`.
    """
    real = _ruta_bd_real()
    forzada = Path(os.environ["INFERBENCH_DB_PATH"]).resolve()

    assert forzada != real.resolve(), f"el arnés apunta a la BD REAL del usuario: {forzada}"
    assert _db.DB_PATH.resolve() == forzada, (
        f"db.DB_PATH ({_db.DB_PATH}) no es la ruta forzada del arnés ({forzada}): "
        "alguien importó `db` antes que este conftest y la BD real está expuesta"
    )
    assert str(real) not in str(
        _db._engine.url
    ), f"el engine de `db` apunta a la BD real: {_db._engine.url}"
    _db.init_db()
    yield

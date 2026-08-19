"""El arnés no puede tocar la base de datos real del usuario.

Regresión de un incidente medido (2026-08-13): tras reiniciar el backend, 135 de las 137
filas de `benchmark_runs` de la BD del usuario quedaron en `interrupted`; 98 de ellas
tenían resultados para TODOS sus prompts, o sea habían terminado bien. El Historial pasó
de verde a ámbar casi entero.

El camino: `TestClient(app)` usado como contexto ARRANCA el lifespan de la app, y el
lifespan llama a `init_db()` y `reconcile_orphan_runs()`. Si el arnés no ha desviado la
base de datos ANTES de que se importe `db` (que resuelve `DB_PATH` al importar), ese
UPDATE cae sobre los datos reales. Está reproducido abajo: `test_el_lifespan_reconcilia_
de_verdad` comprueba que el lifespan SÍ escribe — y los demás, que escribe en la BD
desechable y no en la del usuario.

La red de seguridad de toda la sesión vive en `conftest.py::pytest_sessionfinish`: compara
la BD real byte a byte al final de la suite. Esto de aquí son las aserciones visibles.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import db as db_mod
from db import BenchmarkResult, BenchmarkRun
from main import app

from conftest import _ruta_bd_real

# --- 1. dónde apunta el arnés -----------------------------------------------------------


def test_el_arnes_no_apunta_a_la_bd_real():
    """La aserción que el incidente no tuvo."""
    real = _ruta_bd_real().resolve()

    assert db_mod.DB_PATH.resolve() != real, f"el arnés escribiría en la BD real: {real}"
    assert str(real) not in str(db_mod._engine.url)


def test_la_ruta_se_fuerza_por_entorno_y_no_por_parche():
    """Parchear `db._engine` a posteriori NO basta: el lifespan puede correr antes.

    Por eso el aislamiento va por `INFERBENCH_DB_PATH`, que se lee al construir la ruta.
    """
    forzada = os.environ.get("INFERBENCH_DB_PATH")

    assert forzada, "sin INFERBENCH_DB_PATH el arnés resolvería a backend/data (la real)"
    assert db_mod.DB_PATH.resolve() == Path(forzada).resolve()


def test_sin_la_variable_la_ruta_seria_la_real(monkeypatch):
    """Demuestra que la protección es la variable, no una casualidad del entorno."""
    monkeypatch.delenv("INFERBENCH_DB_PATH", raising=False)

    assert db_mod._db_path().resolve() == _ruta_bd_real().resolve()


# --- 2. el lifespar de la app, que es por donde entró el daño ---------------------------


def _md5_bd_real() -> str | None:
    real = _ruta_bd_real()
    return hashlib.md5(real.read_bytes()).hexdigest() if real.exists() else None


def test_arrancar_la_app_no_toca_la_bd_real():
    """`with TestClient(app)` corre el lifespan: init_db + reconcile. No en la del usuario."""
    antes = _md5_bd_real()
    if antes is None:
        pytest.skip("no hay BD real en esta máquina (CI o clon limpio)")

    with TestClient(app):
        pass

    assert _md5_bd_real() == antes, "el lifespan ha escrito en la base de datos REAL"


def test_el_lifespan_reconcilia_de_verdad():
    """Mata al mutante: si el lifespan no reconciliase, el test de arriba pasaría solo.

    Se comprueba en la BD del arnés que arrancar la app SÍ cierra una run colgada — o sea
    que el peligro que estamos conteniendo existe de verdad.
    """
    with Session(db_mod._engine) as s:
        s.add(
            BenchmarkRun(
                id="aislamiento-colgada",
                ts=int(time.time()),
                engine="llamacpp",
                hw_json="{}",
                opts_json="{}",
                status="running",
            )
        )
        s.commit()

    with TestClient(app):
        pass

    with Session(db_mod._engine) as s:
        assert s.get(BenchmarkRun, "aislamiento-colgada").status == "interrupted"


# --- 3. ninguna fila real cambia de estado ----------------------------------------------


def test_ninguna_fila_de_la_bd_real_cambia_de_estado():
    """Lo que se rompió: los estados del Historial del usuario.

    Compara contra la huella tomada al empezar la sesión (`conftest.pytest_sessionstart`),
    así que cubre todo lo corrido hasta aquí, no solo este módulo.
    """
    from conftest import _HUELLA_INICIAL, _huella

    if _HUELLA_INICIAL is None:
        pytest.skip("no hay BD real en esta máquina (CI o clon limpio)")

    ahora = _huella(_ruta_bd_real())
    assert ahora is not None, "la BD real ha desaparecido"

    antes_estados, ahora_estados = _HUELLA_INICIAL[1], ahora[1]
    cambiadas = {
        rid: (estado, ahora_estados.get(rid, "<BORRADA>"))
        for rid, estado in antes_estados.items()
        if ahora_estados.get(rid) != estado
    }

    assert not cambiadas, f"la suite ha cambiado el estado de runs reales: {cambiadas}"
    assert set(ahora_estados) == set(antes_estados), "la suite ha creado o borrado runs reales"


def test_la_bd_real_ni_siquiera_esta_abierta_por_el_arnes():
    """Nada de escrituras a medias: la BD real no debe tener ni WAL ni journal del arnés."""
    real = _ruta_bd_real()
    if not real.exists():
        pytest.skip("no hay BD real en esta máquina (CI o clon limpio)")

    for sufijo in ("-wal", "-journal"):
        resto = real.with_name(real.name + sufijo)
        assert (
            not resto.exists()
        ), f"el arnés ha dejado {resto.name}: alguien la abrió para escribir"


# --- 4. el conftest se sostiene solo ----------------------------------------------------


def test_la_huella_detecta_un_cambio_de_estado(tmp_path):
    """Mata al mutante del guardián: una huella que siempre dice 'igual' no vale de nada."""
    from conftest import _huella

    bd = tmp_path / "x.sqlite"
    con = sqlite3.connect(bd)
    con.execute("CREATE TABLE benchmark_runs (id TEXT PRIMARY KEY, status TEXT)")
    con.execute("INSERT INTO benchmark_runs VALUES ('r1', 'done')")
    con.commit()
    antes = _huella(bd)

    con.execute("UPDATE benchmark_runs SET status = 'interrupted'")
    con.commit()
    con.close()
    despues = _huella(bd)

    assert antes is not None and despues is not None
    assert antes[0] != despues[0], "el md5 tiene que moverse"
    assert antes[1]["r1"] == "done" and despues[1]["r1"] == "interrupted"


def test_la_huella_de_una_bd_inexistente_es_none(tmp_path):
    from conftest import _huella

    assert _huella(tmp_path / "no-existe.sqlite") is None


@pytest.fixture(autouse=True)
def _limpia_lo_que_escriba_este_modulo():
    yield
    with Session(db_mod._engine) as s:
        for tabla in (BenchmarkResult, BenchmarkRun):  # resultados primero: hay FK
            for fila in s.exec(select(tabla)).all():
                s.delete(fila)
        s.commit()

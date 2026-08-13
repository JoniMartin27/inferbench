"""Tests de las runs que se quedan colgadas en `running`.

El fallo reportado por el usuario: lanza un benchmark, la app se cierra o el backend se
cae, y esa run se queda "en curso" en el Historial **para siempre**, sin forma de pararla.
Reproducido en su máquina: tres filas en `running`, una de ellas de una sesión de días
antes, y las runs nuevas esperando turno detrás de fantasmas.

Dos causas, una por test:
  1. `run.status` solo pasa a `done` si el flujo del runner llega al final. Si el proceso
     muere antes, nadie cierra la fila y no había reconciliación al arrancar.
  2. `POST /{run_id}/stop` devolvía 404 seco cuando el runner no estaba en memoria — o sea
     justo en el caso huérfano. El único botón para pararla no servía.

Ninguno de estos tests ejecuta un modelo: se escribe directamente en la base de datos.
"""

import time

import pytest
from fastapi.testclient import TestClient

import db as db_mod
from db import BenchmarkRun, reconcile_orphan_runs
from main import app


# La base de datos se sustituye a nivel de MÓDULO y ANTES que nada.
#
# La primera versión la parcheaba por test (function scope) mientras el TestClient era de
# módulo: pytest crea los fixtures de módulo primero, así que el lifespan de la app —que
# reconcilia— llegó a correr contra la base de datos REAL del usuario y le cerró sus runs.
# Salió bien de casualidad (eran basura), pero un test jamás debe tocar datos de verdad.
@pytest.fixture(scope="module", autouse=True)
def bd_limpia(tmp_path_factory):
    """Base de datos aparte para todo el módulo: no tocamos la real del usuario."""
    from sqlmodel import SQLModel, create_engine

    ruta = tmp_path_factory.mktemp("bd") / "prueba.sqlite"
    motor = create_engine(f"sqlite:///{ruta}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(motor)
    real_engine, real_path = db_mod._engine, db_mod.DB_PATH
    db_mod._engine, db_mod.DB_PATH = motor, ruta
    yield motor
    db_mod._engine, db_mod.DB_PATH = real_engine, real_path


@pytest.fixture(autouse=True)
def sin_restos(bd_limpia):
    """Cada test empieza sin filas de los anteriores."""
    from sqlmodel import Session, delete

    with Session(bd_limpia) as s:
        s.exec(delete(BenchmarkRun))
        s.commit()
    return bd_limpia


def _fila(motor, run_id, status):
    from sqlmodel import Session

    with Session(motor) as s:
        s.add(
            BenchmarkRun(
                id=run_id,
                ts=int(time.time()),
                engine="llamacpp",
                hw_json="{}",
                opts_json="{}",
                status=status,
            )
        )
        s.commit()


def _estado(motor, run_id):
    from sqlmodel import Session

    with Session(motor) as s:
        return s.get(BenchmarkRun, run_id).status


# --- 1. reconciliación al arrancar ------------------------------------------------------


def test_al_arrancar_se_cierran_las_runs_colgadas(bd_limpia):
    _fila(bd_limpia, "colgada-1", "running")
    _fila(bd_limpia, "colgada-2", "running")

    cerradas = reconcile_orphan_runs()

    assert cerradas == 2
    assert _estado(bd_limpia, "colgada-1") == "interrupted"
    assert _estado(bd_limpia, "colgada-2") == "interrupted"


def test_no_toca_las_runs_ya_terminadas(bd_limpia):
    _fila(bd_limpia, "buena", "done")
    _fila(bd_limpia, "fallada", "error")
    _fila(bd_limpia, "colgada", "running")

    assert reconcile_orphan_runs() == 1

    assert _estado(bd_limpia, "buena") == "done", "una run completada no se toca"
    assert _estado(bd_limpia, "fallada") == "error", "un error no se reescribe"
    assert _estado(bd_limpia, "colgada") == "interrupted"


def test_sin_runs_colgadas_no_hace_nada(bd_limpia):
    _fila(bd_limpia, "buena", "done")
    assert reconcile_orphan_runs() == 0
    assert _estado(bd_limpia, "buena") == "done"


# --- 2. poder pararla desde la API ------------------------------------------------------


# OJO con el orden: `TestClient(app)` ejecuta el lifespan, que RECONCILIA. Si insertas la
# fila antes de entrar al cliente, la reconciliación se la lleva y ya no estás probando el
# `/stop`. Estos tests insertan la fila con el backend YA arrancado, que es el caso real que
# cubre el endpoint: una run que se queda colgada sin reiniciar el proceso.
#
# Y el cliente es uno solo para todo el módulo: el gestor de sesiones de MCP solo se puede
# arrancar una vez por instancia, así que abrir varios TestClient revienta el lifespan.
@pytest.fixture(scope="module")
def cliente(bd_limpia):
    with TestClient(app) as c:
        yield c


def test_parar_una_run_huerfana_ya_no_da_404(bd_limpia, cliente):
    """Es el síntoma exacto: la ves 'en curso' y el botón de parar no sirve."""
    _fila(bd_limpia, "fantasma", "running")

    r = cliente.post("/api/benchmark/fantasma/stop")

    assert r.status_code == 200, "una run colgada TIENE que poder pararse"
    cuerpo = r.json()
    assert cuerpo["cancelled"] is True
    assert cuerpo.get("was_orphan") is True, "y hay que decir que era un fantasma"
    assert _estado(bd_limpia, "fantasma") == "interrupted"


def test_parar_una_run_inexistente_sigue_dando_404(bd_limpia, cliente):
    r = cliente.post("/api/benchmark/no-existe-esta/stop")
    assert r.status_code == 404


def test_parar_una_run_ya_terminada_da_404(bd_limpia, cliente):
    """Terminada no es lo mismo que colgada: no hay nada que cancelar."""
    _fila(bd_limpia, "terminada", "done")
    r = cliente.post("/api/benchmark/terminada/stop")
    assert r.status_code == 404
    assert _estado(bd_limpia, "terminada") == "done"


def test_el_historial_deja_de_ensenarla_en_curso(bd_limpia, cliente):
    """Lo que ve el usuario: tras pararla, ya no pone 'en curso'."""
    _fila(bd_limpia, "fantasma2", "running")

    antes = {r["id"]: r["status"] for r in cliente.get("/api/history").json()}
    assert antes["fantasma2"] == "running", "de partida el Historial la ve en curso"

    cliente.post("/api/benchmark/fantasma2/stop")

    despues = {r["id"]: r["status"] for r in cliente.get("/api/history").json()}
    assert despues["fantasma2"] == "interrupted"

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
from db import (
    BenchmarkResult,
    BenchmarkRun,
    reconcile_orphan_runs,
    repair_misflagged_interrupted_runs,
)
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
        s.exec(delete(BenchmarkResult))  # antes que las runs: hay FK
        s.exec(delete(BenchmarkRun))
        s.commit()
    return bd_limpia


def _fila(motor, run_id, status, prompts=None, resultados=0):
    """Inserta una run. `prompts` son los que declara, `resultados` los que llegó a guardar."""
    import json

    from sqlmodel import Session

    with Session(motor) as s:
        s.add(
            BenchmarkRun(
                id=run_id,
                ts=int(time.time()),
                engine="llamacpp",
                hw_json="{}",
                opts_json=json.dumps({"prompts": prompts}) if prompts else "{}",
                status=status,
            )
        )
        for i in range(resultados):
            s.add(
                BenchmarkResult(
                    run_id=run_id, model_id="m", prompt_id=(prompts or ["p"])[i], tps=1.0
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


# --- 1b. una run con TODOS sus resultados no es huérfana --------------------------------
#
# El daño del incidente del 2026-08-13 no fue marcar de más: fue marcar mal. 98 runs que
# habían terminado enteras acabaron en ámbar. Una fila `running` con resultados para todos
# sus prompts NO se quedó a medias — le faltó el último UPDATE. Decir "interrumpida" ahí es
# tirar trabajo bueno del Historial.


def test_una_run_colgada_pero_con_todos_sus_resultados_se_recupera_como_terminada(bd_limpia):
    _fila(bd_limpia, "acabada", "running", prompts=["chat", "code", "summary"], resultados=3)

    assert reconcile_orphan_runs() == 1, "deja de estar en running, que es lo que se cuenta"

    assert (
        _estado(bd_limpia, "acabada") == "done"
    ), "tenía resultados para todos sus prompts: terminó, no se interrumpió"


def test_una_run_colgada_a_medias_si_se_marca_interrumpida(bd_limpia):
    """El contraste que mata al mutante 'marca done siempre'."""
    _fila(bd_limpia, "a-medias", "running", prompts=["chat", "code", "summary"], resultados=2)

    assert reconcile_orphan_runs() == 1

    assert _estado(bd_limpia, "a-medias") == "interrupted"


def test_una_run_colgada_sin_ningun_resultado_se_marca_interrumpida(bd_limpia):
    _fila(bd_limpia, "vacia", "running", prompts=["chat", "code"], resultados=0)

    assert reconcile_orphan_runs() == 1

    assert _estado(bd_limpia, "vacia") == "interrupted"


def test_se_recuperan_y_se_interrumpen_en_la_misma_pasada(bd_limpia):
    _fila(bd_limpia, "acabada", "running", prompts=["chat"], resultados=1)
    _fila(bd_limpia, "a-medias", "running", prompts=["chat", "code"], resultados=1)

    assert reconcile_orphan_runs() == 2

    assert _estado(bd_limpia, "acabada") == "done"
    assert _estado(bd_limpia, "a-medias") == "interrupted"


# --- 1c. reparación idempotente de las filas que ya quedaron mal marcadas ---------------
#
# Para las máquinas que ya sufrieron el incidente: corre en `init_db()`, en cada arranque.


def test_repara_las_interrumpidas_que_tenian_todos_sus_resultados(bd_limpia):
    _fila(bd_limpia, "mal-marcada", "interrupted", prompts=["chat", "code"], resultados=2)

    assert repair_misflagged_interrupted_runs() == 1

    assert _estado(bd_limpia, "mal-marcada") == "done"


def test_la_reparacion_no_toca_las_interrumpidas_de_verdad(bd_limpia):
    _fila(bd_limpia, "parcial", "interrupted", prompts=["chat", "code"], resultados=1)
    _fila(bd_limpia, "vacia", "interrupted", prompts=["chat"], resultados=0)

    assert repair_misflagged_interrupted_runs() == 0

    assert _estado(bd_limpia, "parcial") == "interrupted"
    assert _estado(bd_limpia, "vacia") == "interrupted"


def test_la_reparacion_es_idempotente(bd_limpia):
    """Corre en cada arranque: la segunda vez no debe encontrar nada que hacer."""
    _fila(bd_limpia, "mal-marcada", "interrupted", prompts=["chat"], resultados=1)

    assert repair_misflagged_interrupted_runs() == 1
    assert repair_misflagged_interrupted_runs() == 0, "la segunda pasada no cambia nada"
    assert _estado(bd_limpia, "mal-marcada") == "done"


def test_la_reparacion_no_toca_runs_en_curso(bd_limpia):
    """Una run viva no es asunto de la reparación."""
    _fila(bd_limpia, "en-curso", "running", prompts=["chat"], resultados=1)

    assert repair_misflagged_interrupted_runs() == 0

    assert _estado(bd_limpia, "en-curso") == "running"


def test_opts_json_ilegible_no_recupera_nada(bd_limpia):
    """Sin poder leer los prompts no se presupone que terminó: fail-closed."""
    from sqlmodel import Session

    _fila(bd_limpia, "rota", "interrupted", prompts=["chat"], resultados=1)
    with Session(bd_limpia) as s:
        fila = s.get(BenchmarkRun, "rota")
        fila.opts_json = "{esto no es json"
        s.add(fila)
        s.commit()

    assert repair_misflagged_interrupted_runs() == 0
    assert _estado(bd_limpia, "rota") == "interrupted"


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

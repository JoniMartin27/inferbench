"""Tests de la caché del sondeo de Docker en core/docker_mgr.py.

Lo que fijan: que con Docker ARRANCADO la app no se vuelva más lenta que con Docker
apagado. `availability()` no tenía caché y `api/engines.py::_runtime_avail` la llama una
vez por motor — cinco motores declaran runtime docker, así que un solo `GET /api/engines`
disparaba cinco sondeos completos (`from_env()` + `ping()` + `version()`, 200-600 ms cada
uno). Medido: `/api/health` 9 ms → 700 ms y `/api/engines` 63 ms → 1,8 s solo por tener
Docker Desktop levantado.
"""

import pytest

from core import docker_mgr as dm


@pytest.fixture(autouse=True)
def limpio():
    dm.invalidate_availability()
    dm._drop_client()
    yield
    dm.invalidate_availability()
    dm._drop_client()


def test_el_sondeo_se_hace_una_sola_vez_dentro_del_ttl(monkeypatch):
    llamadas = []
    monkeypatch.setattr(dm, "_probe_availability", lambda: (llamadas.append(1), {"available": True})[1])

    for _ in range(10):
        assert dm.availability()["available"] is True

    assert len(llamadas) == 1, "diez consultas seguidas deben costar UN solo sondeo"


def test_force_salta_la_cache(monkeypatch):
    llamadas = []
    monkeypatch.setattr(dm, "_probe_availability", lambda: (llamadas.append(1), {"available": True})[1])

    dm.availability()
    dm.availability(force=True)

    assert len(llamadas) == 2


def test_el_ttl_caduca(monkeypatch):
    llamadas = []
    monkeypatch.setattr(dm, "_probe_availability", lambda: (llamadas.append(1), {"available": True})[1])
    reloj = {"t": 1000.0}
    monkeypatch.setattr(dm.time, "monotonic", lambda: reloj["t"])

    dm.availability()
    reloj["t"] += dm._AVAIL_TTL_S / 2
    dm.availability()
    assert len(llamadas) == 1, "dentro del TTL no se re-sondea"

    reloj["t"] += dm._AVAIL_TTL_S
    dm.availability()
    assert len(llamadas) == 2, "pasado el TTL sí se re-sondea"


def test_invalidar_fuerza_un_sondeo_nuevo(monkeypatch):
    llamadas = []
    monkeypatch.setattr(dm, "_probe_availability", lambda: (llamadas.append(1), {"available": True})[1])

    dm.availability()
    dm.invalidate_availability()
    dm.availability()

    assert len(llamadas) == 2


def test_el_cliente_se_reutiliza(monkeypatch):
    creados = []

    class _Cli:
        def ping(self):
            return True

        def close(self):
            pass

    def _from_env():
        creados.append(1)
        return _Cli()

    monkeypatch.setattr(dm, "docker", type("_D", (), {"from_env": staticmethod(_from_env)}))
    for _ in range(5):
        dm._client()

    assert len(creados) == 1, "el cliente Docker no debe recrearse en cada operación"


def test_un_daemon_caido_no_envenena_la_cache_del_cliente(monkeypatch):
    """Si el daemon muere bajo un cliente cacheado, la siguiente llamada debe reconectar."""
    creados = []

    class _Cli:
        def ping(self):
            return True

        def close(self):
            pass

    def _from_env():
        creados.append(1)
        return _Cli()

    monkeypatch.setattr(dm, "docker", type("_D", (), {"from_env": staticmethod(_from_env)}))
    dm._client()
    assert len(creados) == 1

    dm._drop_client()  # es lo que hacen status()/_probe_availability al fallar
    dm._client()

    assert len(creados) == 2, "tras tirar el cliente hay que crear uno nuevo, no reusar el muerto"


def test_status_devuelve_docker_unavailable_si_el_cliente_falla(monkeypatch):
    def _revienta():
        raise dm.DockerUnavailableError("daemon caído")

    monkeypatch.setattr(dm, "_client", _revienta)
    st = dm.status("vllm")

    assert st.state == "docker-unavailable"
    assert st.name == "inferbench-vllm"

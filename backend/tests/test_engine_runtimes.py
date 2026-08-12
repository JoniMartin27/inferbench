"""Tests de cómo `api/engines.py` reporta la disponibilidad del runtime nativo.

Lo que se está fijando: que un motor nativo implementado NO se anuncie como
"No implementado". `stablediffusion` cayó durante meses en el `else` genérico de
`_runtime_availability` aunque `binary_manager` ya sabía responder por él
(`stablediffusion_installed` / `_fully_installed`), así que la UI decía que la
generación de imagen no existía mientras el binario estaba instalado y funcionando.
"""

import pytest

from api import engines as engines_api
from engines import registry


def _nativo(engine_id: str):
    meta = registry.get_engine(engine_id).meta
    disponibles = engines_api._runtime_avail(meta)
    return next((r for r in disponibles if r.runtime == "native"), None)


@pytest.mark.parametrize("engine_id", ["llamacpp", "ollama", "stablediffusion"])
def test_los_motores_nativos_implementados_no_dicen_no_implementado(engine_id, monkeypatch):
    """Instalado o no, un motor implementado nunca debe reportarse como no implementado."""
    nativo = _nativo(engine_id)
    assert nativo is not None, f"{engine_id} declara runtime nativo y debe reportarlo"
    assert nativo.detail != "No implementado", (
        f"{engine_id} está implementado en engines/{engine_id}.py; anunciarlo como "
        f"'No implementado' hace que nadie pruebe la funcionalidad"
    )


def test_stablediffusion_refleja_el_estado_real_del_binario(monkeypatch):
    """El detalle debe seguir a binary_manager, no ser una constante."""
    monkeypatch.setattr(engines_api.binary_manager, "stablediffusion_fully_installed", lambda: True)
    monkeypatch.setattr(engines_api.binary_manager, "stablediffusion_installed", lambda: True)
    nativo = _nativo("stablediffusion")
    assert nativo.ready is True
    assert nativo.detail == "Binario + CUDA listos"

    # Binario presente pero sin las DLLs de CUDA: no está listo, y hay que decir por qué.
    monkeypatch.setattr(
        engines_api.binary_manager, "stablediffusion_fully_installed", lambda: False
    )
    monkeypatch.setattr(engines_api.binary_manager, "stablediffusion_installed", lambda: True)
    nativo = _nativo("stablediffusion")
    assert nativo.ready is False
    assert "CUDA" in nativo.detail

    # Nada instalado: se auto-descarga al primer arranque, así que el mensaje lo dice.
    monkeypatch.setattr(
        engines_api.binary_manager, "stablediffusion_fully_installed", lambda: False
    )
    monkeypatch.setattr(engines_api.binary_manager, "stablediffusion_installed", lambda: False)
    nativo = _nativo("stablediffusion")
    assert nativo.ready is False
    assert nativo.detail == "Listo para descargar"


def test_todo_motor_local_declara_algun_runtime():
    """Ningún motor local puede quedarse sin fila de disponibilidad."""
    for meta in [e.meta for e in registry.list_engines()]:
        if meta.type != "local":
            continue
        disponibles = engines_api._runtime_avail(meta)
        assert disponibles, f"{meta.id} no reporta ningún runtime"
        assert {r.runtime for r in disponibles} == set(meta.runtimes), (
            f"{meta.id} declara runtimes {meta.runtimes} pero reporta "
            f"{[r.runtime for r in disponibles]}"
        )

"""Tests de cómo `api/engines.py` reporta la disponibilidad del runtime nativo.

Lo que se está fijando: que un motor nativo implementado NO se anuncie como
"No implementado". `stablediffusion` cayó durante meses en el `else` genérico de
`_runtime_availability` aunque `binary_manager` ya sabía responder por él
(`stablediffusion_installed` / `_fully_installed`), así que la UI decía que la
generación de imagen no existía mientras el binario estaba instalado y funcionando.

Y, desde el paso a i18n: que cada estado enumerable viaje con su `detail_key` (la UI
traduce por ella) y que el texto de `detail` no vuelva al castellano — es el fallback
en inglés y lo que ven los consumidores de la API.
"""

import re

import pytest

from api import engines as engines_api
from core import compat
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
    assert nativo.detail_key != "notImplemented", (
        f"{engine_id} está implementado en engines/{engine_id}.py; anunciarlo como "
        f"'no implementado' hace que nadie pruebe la funcionalidad"
    )


def test_stablediffusion_refleja_el_estado_real_del_binario(monkeypatch):
    """El detalle debe seguir a binary_manager, no ser una constante."""
    monkeypatch.setattr(engines_api.binary_manager, "stablediffusion_fully_installed", lambda: True)
    monkeypatch.setattr(engines_api.binary_manager, "stablediffusion_installed", lambda: True)
    nativo = _nativo("stablediffusion")
    assert nativo.ready is True
    assert nativo.detail_key == "binaryCudaReady"

    # Binario presente pero sin las DLLs de CUDA: no está listo, y hay que decir por qué.
    monkeypatch.setattr(
        engines_api.binary_manager, "stablediffusion_fully_installed", lambda: False
    )
    monkeypatch.setattr(engines_api.binary_manager, "stablediffusion_installed", lambda: True)
    nativo = _nativo("stablediffusion")
    assert nativo.ready is False
    assert nativo.detail_key == "binaryNoCuda"
    assert "CUDA" in nativo.detail

    # Nada instalado: se auto-descarga al primer arranque, así que el mensaje lo dice.
    monkeypatch.setattr(
        engines_api.binary_manager, "stablediffusion_fully_installed", lambda: False
    )
    monkeypatch.setattr(engines_api.binary_manager, "stablediffusion_installed", lambda: False)
    nativo = _nativo("stablediffusion")
    assert nativo.ready is False
    assert nativo.detail_key == "readyToDownload"


# Vocabulario español distintivo. No hacen falta acentos para colarse: "Binario + CUDA
# listos" y "No implementado" llegaban tal cual a una UI en inglés.
_CASTELLANO = re.compile(
    r"[áéíóúñ¿¡]|\b("
    r"listo|listos|descarga|pendiente|instalado|instalar|arranca|disponible|"
    r"servidor|modelos|propio|calidad|equilibrado|comprimido|agresivo|extremo|"
    r"memoria|menos|mayor|permite|contextos|cuantización|solo"
    r")\b",
    re.IGNORECASE,
)


def _castellano(texto: str) -> str | None:
    m = _CASTELLANO.search(texto or "")
    return m.group(0) if m else None


def test_las_descripciones_de_motor_no_estan_en_castellano():
    """`meta.description` es el fallback de la UI y la doc de la API: va en inglés.

    La UI traduce por `engines.description.<id>`; este texto es lo que se pinta cuando
    aparece un motor que el frontend aún no lista, y lo que ven los clientes de la API.
    """
    for engine in registry.list_engines():
        pista = _castellano(engine.meta.description)
        assert pista is None, (
            f"la descripción de '{engine.meta.id}' parece castellano ({pista!r}): "
            f"{engine.meta.description!r}. El castellano vive en "
            f"frontend/src/i18n/views/engines.js → engines.description.{engine.meta.id}"
        )


def test_los_presets_de_compresion_no_estan_en_castellano():
    """`label`/`desc` viajan en /api/optimize/compression; la UI traduce por el id."""
    for pid, preset in compat.COMPRESSION_PRESETS.items():
        for campo in ("label", "desc"):
            pista = _castellano(preset[campo])
            assert pista is None, (
                f"COMPRESSION_PRESETS['{pid}']['{campo}'] parece castellano ({pista!r}): "
                f"{preset[campo]!r}"
            )


def test_cada_estado_enumerable_del_runtime_trae_clave_i18n():
    """Sin `detail_key` la UI no puede traducir y pinta el inglés del backend.

    Solo se exime el error crudo del SDK de Docker (no es un estado enumerable), que
    llega por `reason` cuando ni siquiera hay `hint`.
    """
    for meta in [e.meta for e in registry.list_engines()]:
        for disp in engines_api._runtime_avail(meta):
            assert disp.detail, f"{meta.id}/{disp.runtime} no reporta detalle"
            if disp.runtime == "native":
                assert disp.detail_key, (
                    f"{meta.id}/native manda '{disp.detail}' sin detail_key: la UI en "
                    f"español lo pintaría en inglés"
                )
            assert _castellano(disp.detail) is None, (
                f"{meta.id}/{disp.runtime} manda castellano en detail: {disp.detail!r}"
            )


def test_docker_apagado_trae_clave_traducible(monkeypatch):
    """El `hint` de Docker sí es enumerable, así que debe llegar con su clave."""
    monkeypatch.setattr(
        engines_api.docker_mgr,
        "availability",
        lambda: {
            "available": False,
            "installed": True,
            "reason": "error while fetching server api version",
            "hint": "Start Docker Desktop",
            "hint_key": "startDockerDesktop",
        },
    )
    meta = registry.get_engine("vllm").meta
    docker = next(r for r in engines_api._runtime_avail(meta) if r.runtime == "docker")
    assert docker.ready is False
    assert docker.detail_key == "startDockerDesktop"


def test_docker_en_marcha_publica_la_version_como_parametro(monkeypatch):
    """El chip dice "Docker 27.1.1": la versión va en params, no incrustada en la clave."""
    monkeypatch.setattr(
        engines_api.docker_mgr,
        "availability",
        lambda: {"available": True, "installed": True, "version": "27.1.1"},
    )
    meta = registry.get_engine("vllm").meta
    docker = next(r for r in engines_api._runtime_avail(meta) if r.runtime == "docker")
    assert docker.ready is True
    assert docker.detail_key == "dockerVersion"
    assert docker.detail_params == {"version": "27.1.1"}


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

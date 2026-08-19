"""La recomendación usa el daño MEDIDO cuando existe, y no inventa nada cuando no.

El piso de calidad del Dashboard se apoyaba solo en bits/peso, que es una heurística
prestada de la literatura. Desde el #50 inferbench MIDE el daño real de cada cuantización
(perplejidad + KL contra una referencia), pero esa medida no llegaba a la recomendación:
se quedaba en un JSON que nadie leía. Aquí se ata el puente entre las dos cosas.
"""

from __future__ import annotations

import json

import pytest
from core import perplexity as ppl
from core.optimizer import ENGINE_QUANTS

# Comparación real de esta máquina (Llama-3.2-1B, referencia Q8_0) más tres casos límite
# que solo se distinguen si el código los trata aparte: una medida que falló, una guardada
# en minúsculas y una sin `same_top_pct`.
_MEDIDAS = [
    {"quant": "Q8_0", "ppl": 20.4026, "es_referencia": True, "same_top_pct": None},
    {
        "quant": "Q6_K",
        "ppl_ratio": 1.005391,
        "kld_media": 0.015439,
        "same_top_pct": 92.449,
        "es_referencia": False,
        "error": None,
    },
    # Guardada en minúsculas: los nombres vienen del fichero GGUF, y ahí no hay una sola
    # convención (`...-q4_k_m.gguf` existe en repos reales).
    {
        "quant": "q5_k_m",
        "ppl_ratio": 1.012271,
        "same_top_pct": 89.652,
        "es_referencia": False,
        "error": None,
    },
    {
        "quant": "Q4_K_M",
        "ppl_ratio": 1.053493,
        "kld_media": 0.07931,
        "same_top_pct": 83.618,
        "es_referencia": False,
        "error": None,
    },
    # Falló a mitad y dejó una cifra a medias: si no se mira `error`, se publicaría como
    # buena una medida que nadie completó.
    {"quant": "Q3_K_M", "es_referencia": False, "same_top_pct": 50.0, "error": "OOM"},
    # Terminó, pero sin la parte de KL: sin `same_top_pct` no hay nada que enseñar.
    {"quant": "IQ4_XS", "ppl_ratio": 1.12, "same_top_pct": None, "es_referencia": False},
]

# Para el test por HTTP: da igual qué cuantización elija el optimizador en la máquina que
# corra los tests, siempre habrá medida. Sin esto el test dependía del hardware.
_TODOS_LOS_QUANTS = [
    {
        "quant": q,
        "ppl_ratio": 1.05,
        "kld_media": 0.08,
        "same_top_pct": 80.0,
        "es_referencia": False,
        "error": None,
    }
    for q in ENGINE_QUANTS["llamacpp"]
    if q not in {"Q8_0", "Q6_K", "Q4_K_M", "Q3_K_M", "IQ4_XS"}
]

_COMPARACION = {
    "modelo": "Llama-3.2-1B-Instruct",
    "referencia": "Q8_0",
    "medidas": _MEDIDAS + _TODOS_LOS_QUANTS,
}


@pytest.fixture
def medidas(tmp_path, monkeypatch):
    """Apunta la persistencia a un fichero desechable: los tests no miran el %APPDATA% real."""
    f = tmp_path / "quant_damage.json"
    f.write_text(json.dumps([_COMPARACION]), encoding="utf-8")
    monkeypatch.setattr(ppl, "fichero_resultados", lambda: f)
    return f


# --- el puente catálogo → medida ------------------------------------------------------


def test_el_nombre_del_catalogo_casa_con_el_del_fichero_gguf():
    assert (
        ppl.modelo_base_de_plantilla("Llama-3.2-1B-Instruct-{quant}.gguf")
        == "Llama-3.2-1B-Instruct"
    )


def test_sin_plantilla_no_hay_puente():
    assert ppl.modelo_base_de_plantilla(None) is None


def test_devuelve_la_medida_del_quant_pedido(medidas):
    d = ppl.dano_medido("Llama-3.2-1B-Instruct", "Q4_K_M")
    assert d["same_top_pct"] == 83.618
    assert d["referencia"] == "Q8_0"
    assert d["es_referencia"] is False


def test_el_quant_no_distingue_mayusculas(medidas):
    """En los dos sentidos: la consulta y lo GUARDADO pueden venir en cualquier caja."""
    assert ppl.dano_medido("Llama-3.2-1B-Instruct", "q6_k")["same_top_pct"] == 92.449
    assert ppl.dano_medido("Llama-3.2-1B-Instruct", "Q5_K_M")["same_top_pct"] == 89.652


def test_la_referencia_no_se_puntua_contra_si_misma(medidas):
    """Decir "100% de coincidencia" sería inventarse una medida que nadie ha hecho."""
    d = ppl.dano_medido("Llama-3.2-1B-Instruct", "Q8_0")
    assert d["es_referencia"] is True
    assert "same_top_pct" not in d


def test_una_medida_que_fallo_no_cuenta(medidas):
    """Q3_K_M dejó un 50,0 a medias antes de morir: publicarlo sería peor que no medir."""
    assert ppl.dano_medido("Llama-3.2-1B-Instruct", "Q3_K_M") is None


def test_una_medida_sin_coincidencia_de_token_no_cuenta(medidas):
    """IQ4_XS tiene perplejidad pero no KL: media medida no es una medida."""
    assert ppl.dano_medido("Llama-3.2-1B-Instruct", "IQ4_XS") is None


def test_quant_no_medido_es_none(medidas):
    assert ppl.dano_medido("Llama-3.2-1B-Instruct", "NO_EXISTE_Q") is None


def test_modelo_no_medido_es_none(medidas):
    assert ppl.dano_medido("Meta-Llama-3.1-8B-Instruct", "Q4_K_M") is None


def test_sin_modelo_o_sin_quant_es_none(medidas):
    assert ppl.dano_medido(None, "Q4_K_M") is None
    assert ppl.dano_medido("Llama-3.2-1B-Instruct", None) is None


def test_fichero_ausente_no_revienta(tmp_path, monkeypatch):
    monkeypatch.setattr(ppl, "fichero_resultados", lambda: tmp_path / "no-existe.json")
    assert ppl.dano_medido("Llama-3.2-1B-Instruct", "Q4_K_M") is None


def test_fichero_corrupto_no_revienta(tmp_path, monkeypatch):
    f = tmp_path / "quant_damage.json"
    f.write_text("{esto no es json", encoding="utf-8")
    monkeypatch.setattr(ppl, "fichero_resultados", lambda: f)
    assert ppl.cargar_resultados() == []
    assert ppl.dano_medido("Llama-3.2-1B-Instruct", "Q4_K_M") is None


# --- llega hasta la API ---------------------------------------------------------------


def test_la_recomendacion_expone_la_medida(medidas):
    """Por HTTP, que es como lo ve el Dashboard: no vale con que la función interna acierte."""
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as c:
        r = c.get("/api/optimize/recommendations", params={"top": 500})
        assert r.status_code == 200
        filas = r.json()

    assert filas, "sin recomendaciones no se puede comprobar nada"
    assert all("measured_damage" in f for f in filas)

    medido = [f for f in filas if f["model"]["id"] == "llama-3.2-1b"]
    assert medido, "llama-3.2-1b debería caber en cualquier máquina que corra los tests"
    d = medido[0]["measured_damage"]
    assert d is not None, "hay medida para todas sus cuantizaciones: la API tiene que traerla"
    assert d["referencia"] == "Q8_0"

    # Y un modelo sin medir NO inventa daño.
    sin_medir = [f for f in filas if f["model"]["id"] != "llama-3.2-1b"]
    assert all(f["measured_damage"] is None for f in sin_medir)

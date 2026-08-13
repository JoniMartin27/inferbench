"""La config que de verdad se ejecutó tiene que quedar guardada en el run.

Con `auto=true` el contexto y la KV-cache los elige el planificador al arrancar el motor:
si no se persisten, el Historial no puede decir con qué configuración se midió (salían `—`
en las columnas KV y CTX de la comparación en todas las runs automáticas).
"""

import json

from api.benchmark import _merge_resolved_opts

RESUELTO = {"contextLen": 8192, "kvCacheK": "f16", "kvCacheV": "f16", "ngl": 999}


def test_guarda_la_config_resuelta_cuando_no_habia_engine_opts():
    opts = json.dumps({"engine": "llamacpp", "model": "llama-3.2-1b", "engine_opts": {}})
    out = json.loads(_merge_resolved_opts(opts, RESUELTO))
    assert out["engine_opts"]["contextLen"] == 8192
    assert out["engine_opts"]["kvCacheK"] == "f16"
    # y no se lleva por delante el resto del cuerpo
    assert out["model"] == "llama-3.2-1b"


def test_lo_ejecutado_manda_sobre_lo_pedido():
    # El usuario pidió 4096 pero el planificador acabó corriendo con 8192: lo que hay que
    # poder leer luego es lo que pasó de verdad.
    opts = json.dumps({"engine_opts": {"contextLen": 4096, "mlock": True}})
    out = json.loads(_merge_resolved_opts(opts, RESUELTO))
    assert out["engine_opts"]["contextLen"] == 8192
    # las claves que el plan no toca se conservan
    assert out["engine_opts"]["mlock"] is True


def test_sin_config_resuelta_no_toca_nada():
    # Motores que no pasan por el planificador de llama.cpp (Docker, APIs cloud).
    opts = json.dumps({"engine": "openai", "engine_opts": {}})
    assert _merge_resolved_opts(opts, {}) == opts


def test_json_ilegible_no_rompe_la_persistencia():
    # Preferimos perder la config resuelta antes que perder el run entero.
    assert _merge_resolved_opts("{esto no es json", RESUELTO) == "{esto no es json"
    assert _merge_resolved_opts(None, RESUELTO) is None


def test_opts_que_no_son_un_objeto_se_dejan_como_estan():
    assert _merge_resolved_opts("[1, 2, 3]", RESUELTO) == "[1, 2, 3]"

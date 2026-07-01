"""Tests del rigor de benchmark: migración de DB, métricas nuevas del resultado y la
derivación de cuantizaciones disponibles (para el mensaje de error enriquecido)."""

from __future__ import annotations

import asyncio
import sqlite3

from core.benchmark import BenchmarkRequest, BenchmarkRunner, ResultPayload, get_prompt
from core.model_manager import _quants_from_filenames


def test_result_payload_has_rigor_fields_with_defaults():
    r = ResultPayload(
        model_id="m",
        prompt_id="chat",
        tps=100.0,
        ttft_ms=200,
        vram_gb=3.0,
        ram_gb=8.0,
        quality=90.0,
        cost=0.0,
        ctx_used=128,
        raw_output="hola",
    )
    # Defaults razonables cuando no se especifican (compatibilidad hacia atrás).
    assert r.prefill_tps == 0.0
    assert r.tps_std == 0.0
    assert r.ttft_std == 0.0
    assert r.n_samples == 1
    # Y se pueden poblar con la agregación de varias muestras.
    r2 = ResultPayload(
        model_id="m",
        prompt_id="chat",
        tps=350.0,
        ttft_ms=290,
        vram_gb=3.3,
        ram_gb=16.0,
        quality=80.0,
        cost=0.0,
        ctx_used=128,
        raw_output="x",
        prefill_tps=340.0,
        tps_std=4.1,
        ttft_std=5.7,
        n_samples=3,
    )
    assert r2.n_samples == 3 and r2.prefill_tps == 340.0


def test_db_migration_is_idempotent_and_adds_columns(tmp_path, monkeypatch):
    import db as dbmod

    # Apunta la DB a un fichero temporal y recrea el engine sobre él.
    from sqlmodel import create_engine

    db_path = tmp_path / "t.sqlite"
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    monkeypatch.setattr(
        dbmod,
        "_engine",
        create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False}),
    )

    # Simula una tabla "vieja" SIN las columnas nuevas, para probar el ALTER.
    con = sqlite3.connect(db_path)
    con.execute(
        "CREATE TABLE benchmark_results (id INTEGER PRIMARY KEY, run_id TEXT, "
        "model_id TEXT, prompt_id TEXT, tps FLOAT, ttft_ms INTEGER)"
    )
    con.commit()
    con.close()

    dbmod.init_db()  # primera migración: añade columnas
    dbmod.init_db()  # idempotente: no debe fallar al re-ejecutarse

    con = sqlite3.connect(db_path)
    cols = {row[1] for row in con.execute("PRAGMA table_info(benchmark_results)")}
    con.close()
    for col in ("prefill_tps", "tps_std", "ttft_std", "n_samples"):
        assert col in cols, f"falta la columna migrada {col}"


def test_quants_from_filenames_bartowski_dash():
    tmpl = "Qwen_Qwen3-4B-{quant}.gguf"
    files = [
        "Qwen_Qwen3-4B-Q4_K_M.gguf",
        "Qwen_Qwen3-4B-Q8_0.gguf",
        "Qwen_Qwen3-4B-IQ2_XS.gguf",
        "README.md",  # ruido: no casa
        "Qwen_Qwen3-4B-mmproj-f16.gguf",  # projector: no es un quant válido del patrón base
    ]
    quants = _quants_from_filenames(tmpl, files)
    # Ordenadas por calidad descendente.
    assert quants[0] == "Q8_0"
    assert "Q4_K_M" in quants
    assert "IQ2_XS" in quants
    # El mmproj no debe colarse como cuantización Q*/IQ*.
    assert "mmproj-f16" not in quants


def test_quants_from_filenames_thebloke_dot_lowercase():
    tmpl = "tinyllama-1.1b-chat-v1.0.{quant}.gguf"
    files = [
        "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        "tinyllama-1.1b-chat-v1.0.Q2_K.gguf",
    ]
    quants = _quants_from_filenames(tmpl, files)
    assert quants == ["Q4_K_M", "Q2_K"]  # Q4_K_M ordena antes que Q2_K


def test_quants_from_filenames_subdir_prefix_ignored():
    # Algunos repos sirven el fichero bajo un subdir; solo importa el basename.
    tmpl = "model-{quant}.gguf"
    files = ["main/model-Q4_K_M.gguf", "model-Q6_K.gguf"]
    quants = _quants_from_filenames(tmpl, files)
    assert set(quants) == {"Q4_K_M", "Q6_K"}


def test_run_one_emits_result_event_when_base_url_missing():
    # Si el motor no tiene base_url resuelta, _run_one debe registrar Y EMITIR un evento
    # "result" (como el camino normal), no solo loguear el error — si no, el panel en vivo
    # se queda sin esa fila aunque sí termine persistida en la DB al acabar la run.
    req = BenchmarkRequest(engine="unknown-engine", model="m", prompts=["chat"], auto=False)
    runner = BenchmarkRunner(req)
    assert runner.base_url is None
    prompt = get_prompt("chat")
    assert prompt is not None

    asyncio.run(runner._run_one(prompt, {}))

    assert len(runner.results) == 1
    assert runner.results[0].error

    events = []
    while not runner.queue.empty():
        events.append(runner.queue.get_nowait())
    result_events = [e for e in events if e["type"] == "result"]
    assert len(result_events) == 1
    assert result_events[0]["result"]["error"] == runner.results[0].error

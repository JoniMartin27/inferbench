"""Tests del exporter de spans a lookspan (construcción + contrato de ingest, sin red)."""

from types import SimpleNamespace

from core import lookspan


def _result(**kw):
    base = dict(
        model_id="m",
        prompt_id="reasoning",
        tps=100.0,
        ttft_ms=200,
        vram_gb=4.0,
        ram_gb=8.0,
        quality=80.0,
        cost=0.0,
        ctx_used=256,
        raw_output="hola",
        error="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_endpoint_opt_in(monkeypatch):
    monkeypatch.delenv("LOOKSPAN_ENDPOINT", raising=False)
    assert lookspan.endpoint() is None
    monkeypatch.setenv("LOOKSPAN_ENDPOINT", "http://127.0.0.1:3100/api/ingest")
    assert lookspan.endpoint() == "http://127.0.0.1:3100/api/ingest"
    monkeypatch.setenv("LOOKSPAN_ENDPOINT", "http://127.0.0.1:3100")  # base sin path → se completa
    assert lookspan.endpoint() == "http://127.0.0.1:3100/api/ingest"


def test_build_spans_root_and_children():
    results = [
        _result(prompt_id="reasoning"),
        _result(prompt_id="code", error="boom", tps=0, ctx_used=0),
    ]
    spans = lookspan.build_spans(
        "run123", "llamacpp", "llama-3-8b", "Q4_K_M", results, 1000.0, 1010.0, {"kvCacheK": "q8_0"}
    )
    assert len(spans) == 3  # raíz + 2 prompts
    root = spans[0]
    assert root["type"] == "custom" and root["parentSpanId"] is None
    assert root["framework"] == "inferbench" and root["traceId"] == "run123"
    assert root["status"] == "ok"  # hay al menos un prompt ok
    assert root["attributes"]["kvCacheK"] == "q8_0"

    children = spans[1:]
    assert all(c["parentSpanId"] == root["spanId"] for c in children)
    assert all(c["type"] == "llm_call" and c["traceId"] == "run123" for c in children)

    err = next(c for c in children if c["input"]["prompt_id"] == "code")
    assert err["status"] == "error" and err["error"]["message"] == "boom"

    ok = next(c for c in children if c["input"]["prompt_id"] == "reasoning")
    assert ok["attributes"]["tps"] == 100.0 and ok["attributes"]["quality"] == 80.0
    assert ok["usage"]["outputTokens"] == 256


def test_build_spans_match_ingest_contract():
    # Mismas reglas que lookspan/collector/normalize.ts
    spans = lookspan.build_spans("r", "vllm", "m", "fp8", [_result()], 1.0, 2.0)
    valid_types = {"agent_step", "llm_call", "tool_call", "error", "custom"}
    valid_status = {"ok", "error", "cancelled"}
    for sp in spans:
        for f in ("traceId", "spanId", "type", "name", "startedAt", "status", "framework"):
            assert isinstance(sp[f], str) and sp[f], f
        assert sp["type"] in valid_types
        assert sp["status"] in valid_status
        assert sp["parentSpanId"] is None or isinstance(sp["parentSpanId"], str)


def test_build_spans_handles_none_ttft():
    # ttft_ms=None es válido en el modelo de DB (BenchmarkResult.ttft_ms: int | None); build_spans
    # no debe reventar con TypeError al dividir None entre 1000.0 (regresión).
    spans = lookspan.build_spans(
        "r", "llamacpp", "m", "Q4_K_M", [_result(ttft_ms=None, tps=None, ctx_used=None)], 1.0, 2.0
    )
    assert len(spans) == 2


async def test_export_run_never_raises_on_bad_result(monkeypatch):
    # Si build_spans lanzase por un dato inesperado en `results`, el contrato de export_run
    # ("fire-and-forget, nunca rompe el benchmark") exige que se trague igual que un fallo de
    # red — antes la construcción del payload quedaba FUERA del try/except.
    monkeypatch.setenv("LOOKSPAN_ENDPOINT", "http://127.0.0.1:3100")

    class _Evil:
        @property
        def error(self):
            raise RuntimeError("boom: dato inesperado")

    await lookspan.export_run("r", "llamacpp", "m", "Q4_K_M", [_Evil()], 1.0, 2.0)  # no debe lanzar

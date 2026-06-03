"""Exporter opt-in de spans de benchmark a lookspan (observabilidad local).

Cada run de benchmark se exporta como un TRACE: un span raíz (`custom`) con un span hijo
(`llm_call`) por cada prompt, llevando las métricas REALES (TTFT, tok/s, VRAM, calidad).
Best-effort y fire-and-forget: un fallo de red se loguea y se traga — la telemetría NUNCA
rompe ni ralentiza un benchmark.

Opt-in: solo actúa si está `LOOKSPAN_ENDPOINT` (p.ej. http://127.0.0.1:3100/api/ingest),
la misma convención que usa AGENT-OS. Sin esa env, es un no-op de coste cero.

Contrato del ingest (lookspan/packages/types + collector/normalize): POST {spans, source,
sentAt}; cada span necesita traceId/spanId/type/name/startedAt/status/framework como strings
no vacíos; type ∈ {agent_step, llm_call, tool_call, error, custom}; status ∈ {ok, error,
cancelled}. El `framework` no se valida contra un enum → usamos "inferbench".
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger


def endpoint() -> str | None:
    """URL de ingest de lookspan, o None si la observabilidad está desactivada (opt-in)."""
    ep = os.environ.get("LOOKSPAN_ENDPOINT")
    if not ep:
        return None
    ep = ep.rstrip("/")
    # Aceptar tanto la URL completa como solo la base (http://host:3100).
    return ep if "/ingest" in ep else f"{ep}/api/ingest"


def _sid() -> str:
    return uuid.uuid4().hex[:16]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def build_spans(
    run_id: str,
    engine: str,
    model: str,
    quant: str,
    results: list[Any],
    started_ts: float,
    ended_ts: float,
    engine_opts: dict | None = None,
) -> list[dict]:
    """Construye los spans de un run: raíz `custom` + un `llm_call` por prompt."""
    results = list(results)
    any_ok = any(not getattr(r, "error", "") for r in results)
    any_err = any(getattr(r, "error", "") for r in results)
    root_id = _sid()
    root = {
        "traceId": run_id,
        "spanId": root_id,
        "parentSpanId": None,
        "type": "custom",
        "name": f"benchmark {model} · {engine} ({quant})",
        "startedAt": _iso(started_ts),
        "endedAt": _iso(ended_ts),
        "status": "error" if (any_err and not any_ok) else "ok",
        "framework": "inferbench",
        "model": model,
        "provider": engine,
        "attributes": {
            "quant": quant,
            "prompts": len(results),
            **{k: v for k, v in (engine_opts or {}).items() if isinstance(v, (str, int, float, bool))},
        },
    }
    spans: list[dict] = [root]

    # Reconstruimos el waterfall a partir de las duraciones medidas (TTFT + generación) y lo
    # alineamos para que termine en ended_ts (queda DESPUÉS del bootstrap/descarga).
    def _dur(r) -> float:
        tps = getattr(r, "tps", 0) or 0
        toks = getattr(r, "ctx_used", 0) or 0
        return max(getattr(r, "ttft_ms", 0) / 1000.0 + (toks / tps if tps else 0.0), 0.01)

    total = sum(_dur(r) for r in results)
    cursor = max(started_ts, ended_ts - total)
    for r in results:
        d = _dur(r)
        err = getattr(r, "error", "") or ""
        spans.append({
            "traceId": run_id,
            "spanId": _sid(),
            "parentSpanId": root_id,
            "type": "llm_call",
            "name": f"{getattr(r, 'prompt_id', '?')} · {model}",
            "startedAt": _iso(cursor),
            "endedAt": _iso(cursor + d),
            "status": "error" if err else "ok",
            "framework": "inferbench",
            "model": getattr(r, "model_id", model) or model,
            "provider": engine,
            "input": {"prompt_id": getattr(r, "prompt_id", None)},
            "output": (getattr(r, "raw_output", "") or "")[:2000] or None,
            "error": {"message": err} if err else None,
            "usage": {
                "inputTokens": 0,
                "outputTokens": int(getattr(r, "ctx_used", 0) or 0),
                "costUsd": float(getattr(r, "cost", 0.0) or 0.0),
            },
            "attributes": {
                "ttft_ms": getattr(r, "ttft_ms", None),
                "tps": getattr(r, "tps", None),
                "vram_gb": getattr(r, "vram_gb", None),
                "ram_gb": getattr(r, "ram_gb", None),
                "quality": getattr(r, "quality", None),
                "prompt_id": getattr(r, "prompt_id", None),
                "quant": quant,
            },
        })
    return spans


async def export_run(
    run_id: str,
    engine: str,
    model: str,
    quant: str,
    results: list[Any],
    started_ts: float,
    ended_ts: float,
    engine_opts: dict | None = None,
) -> None:
    """Exporta el run a lookspan si hay endpoint. Fire-and-forget (no lanza)."""
    ep = endpoint()
    if not ep or not results:
        return
    payload = {
        "spans": build_spans(run_id, engine, model, quant, results, started_ts, ended_ts, engine_opts),
        "source": "inferbench",
        "sentAt": _iso(datetime.now(tz=timezone.utc).timestamp()),
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.post(ep, json=payload)
        if resp.status_code >= 400:
            logger.warning(f"[lookspan] ingest {resp.status_code}: {resp.text[:200]}")
        else:
            logger.info(f"[lookspan] exportado run {run_id} ({len(results)} spans) → {ep}")
    except Exception as e:
        logger.warning(f"[lookspan] export falló ({e}); el benchmark no se ve afectado")

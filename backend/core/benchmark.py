"""Ejecución automática de benchmarks: bootstrap (binario+modelo+motor) → benchmark → teardown.

Eventos SSE emitidos:
  start, log, phase
  engine.install (con pct), model.download (con pct), engine.start, engine.ready
  phase (load|warmup|ttft|generate|quality), tokens, result, done
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import psutil
from loguru import logger
from pydantic import BaseModel, Field

from . import binary_manager, model_manager, native_runtime
from .hardware import detect_hardware
from .models_catalog import Model, get_model
from .optimizer import get_optimal_config

PROMPTS_FILE = Path(__file__).resolve().parent.parent / "data" / "prompts.json"


class Prompt(BaseModel):
    id: str
    name: str
    type: str
    system: str = ""
    prompt: str
    target_tokens: int = 256
    reference: str = ""


def load_prompts() -> list[Prompt]:
    raw = json.loads(PROMPTS_FILE.read_text(encoding="utf-8"))
    return [Prompt.model_validate(p) for p in raw]


def get_prompt(prompt_id: str) -> Prompt | None:
    for p in load_prompts():
        if p.id == prompt_id:
            return p
    return None


DEFAULT_BASE_URLS: dict[str, str] = {
    "llamacpp": "http://localhost:8080",
    "vllm": "http://localhost:8000",
    "sglang": "http://localhost:30000",
    "tgi": "http://localhost:8088",
    "ollama": "http://localhost:11434",
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
    "openrouter": "https://openrouter.ai/api",
    "nvidia": "https://integrate.api.nvidia.com",
}

API_ENGINES = {"openai", "anthropic", "openrouter", "nvidia"}


class BenchmarkRequest(BaseModel):
    engine: str
    model: str
    quant: str = "Q4_K_M"
    prompts: list[str] = Field(default_factory=lambda: ["reasoning", "code", "summary", "chat"])
    auto: bool = True              # bootstrap automático del motor + descarga del modelo
    keep_alive: bool = False       # si True, no detiene el motor al terminar
    base_url: str | None = None    # override manual (si auto=false)
    api_key: str | None = None
    sampling: dict[str, Any] = Field(default_factory=lambda: {"temperature": 0.7, "top_p": 0.95})
    notes: str = ""


class ResultPayload(BaseModel):
    model_id: str
    prompt_id: str
    tps: float
    ttft_ms: int
    vram_gb: float
    ram_gb: float
    quality: float
    cost: float
    ctx_used: int
    raw_output: str
    error: str = ""


def _get_vram_used_gb() -> float:
    try:
        import pynvml  # type: ignore
        pynvml.nvmlInit()
        try:
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            return round(mem.used / (1024**3), 2)
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return 0.0


def _quality_heuristic(output: str, ref: str) -> float:
    if not output.strip():
        return 0.0
    base = min(60.0, len(output) / 8.0)
    if ref:
        ref_words = {w.lower() for w in ref.split() if len(w) > 3}
        if ref_words:
            out_words = {w.lower() for w in output.split() if len(w) > 3}
            overlap = len(ref_words & out_words) / len(ref_words)
            base += overlap * 40.0
    return min(100.0, round(base, 1))


async def _stream_openai_chat(
    base_url: str,
    model_id_for_engine: str,
    prompt: Prompt,
    sampling: dict[str, Any],
    headers: dict[str, str],
) -> AsyncIterator[tuple[str, Any]]:
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    body = {
        "model": model_id_for_engine,
        "messages": [
            {"role": "system", "content": prompt.system} if prompt.system else None,
            {"role": "user", "content": prompt.prompt},
        ],
        "max_tokens": prompt.target_tokens,
        "stream": True,
        **sampling,
    }
    body["messages"] = [m for m in body["messages"] if m]

    first = True
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
        async with client.stream("POST", url, json=body, headers=headers) as resp:
            if resp.status_code >= 400:
                text = await resp.aread()
                raise RuntimeError(
                    f"HTTP {resp.status_code}: {text.decode(errors='replace')[:500]}"
                )
            async for line in resp.aiter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                    content = delta.get("content") or ""
                    if content:
                        if first:
                            yield ("first_token", content)
                            first = False
                        else:
                            yield ("token", content)
    yield ("done", None)


async def _wait_engine_ready(base_url: str, timeout: float = 90.0) -> None:
    """Espera a que el endpoint /v1/models responda 200."""
    deadline = time.time() + timeout
    last_err = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        while time.time() < deadline:
            try:
                r = await client.get(f"{base_url.rstrip('/')}/v1/models")
                if r.status_code == 200:
                    return
                last_err = f"HTTP {r.status_code}"
            except Exception as e:
                last_err = str(e)
            await asyncio.sleep(1.0)
    raise RuntimeError(f"Motor no listo tras {timeout}s ({last_err})")


class BenchmarkRunner:
    """Orquesta una corrida con bootstrap automático y eventos SSE vía asyncio.Queue."""

    def __init__(self, req: BenchmarkRequest):
        self.req = req
        self.run_id = uuid.uuid4().hex[:12]
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.results: list[ResultPayload] = []
        self.hw = detect_hardware()
        self.is_api = req.engine in API_ENGINES
        self.base_url = req.base_url or DEFAULT_BASE_URLS.get(req.engine)
        self._owns_engine = False  # si nosotros arrancamos el motor, lo paramos al final

    async def emit(self, evt: dict[str, Any]) -> None:
        await self.queue.put(evt)

    async def run(self) -> None:
        try:
            prompts = [p for p in (get_prompt(pid) for pid in self.req.prompts) if p]
            await self.emit({"type": "start", "run_id": self.run_id, "total": len(prompts)})

            if self.req.auto and not self.is_api:
                try:
                    await self._bootstrap()
                except Exception as e:
                    logger.exception("bootstrap failed")
                    await self.emit({"type": "log", "level": "error", "text": f"Bootstrap: {e}"})
                    await self.emit({"type": "done", "run_id": self.run_id, "error": str(e)})
                    return

            headers = {"Content-Type": "application/json"}
            if self.req.api_key:
                headers["Authorization"] = f"Bearer {self.req.api_key}"

            for prompt in prompts:
                await self._run_one(prompt, headers)

            await self.emit({"type": "done", "run_id": self.run_id})
        except Exception as e:
            logger.exception("benchmark failed")
            await self.emit({"type": "log", "level": "error", "text": f"Fatal: {e}"})
            await self.emit({"type": "done", "run_id": self.run_id, "error": str(e)})
        finally:
            if self._owns_engine and not self.req.keep_alive:
                try:
                    await self.emit({"type": "log", "level": "info", "text": "Deteniendo motor…"})
                    native_runtime.stop(self.req.engine)
                except Exception:
                    pass
            await self.queue.put({"type": "_eof"})

    async def _bootstrap(self) -> None:
        """Asegura: binario nativo + modelo GGUF + motor corriendo."""
        if self.req.engine != "llamacpp":
            raise RuntimeError(
                f"Auto-bootstrap solo soportado para llamacpp por ahora. "
                f"Para {self.req.engine}, pasa base_url manual."
            )

        model = get_model(self.req.model)
        if model is None:
            raise RuntimeError(f"Modelo desconocido: {self.req.model}")

        # 1. Binario nativo + DLLs CUDA si aplica
        # install_llamacpp es idempotente: descarga solo lo que falte (binario y/o cudart)
        async def bin_progress(evt):
            await self.emit({"type": "engine.install", **evt})

        if not binary_manager.llamacpp_fully_installed():
            await self.emit({"type": "log", "level": "info", "text": "Preparando llama.cpp…"})
            await binary_manager.install_llamacpp(progress=bin_progress)
            await self.emit({"type": "log", "level": "success", "text": "Binario listo"})
        binary = binary_manager.llamacpp_binary_path()

        # 2. Modelo GGUF
        if not model.hf_gguf:
            raise RuntimeError(
                f"El modelo {model.id} no tiene fuente HF GGUF. Selecciona otro o pasa base_url manual."
            )
        if not model_manager.gguf_installed(model, self.req.quant):
            size_hint_gb = model.size_base_gb * 0.55 / 2.0  # estimación Q4_K_M
            await self.emit({
                "type": "log",
                "level": "info",
                "text": f"Descargando GGUF {self.req.quant} (~{size_hint_gb:.1f}GB)…",
            })

            async def model_progress(evt):
                await self.emit({"type": "model.download", **evt})

            try:
                await model_manager.ensure_gguf(model, self.req.quant, progress=model_progress)
            except RuntimeError as e:
                # Probable: cuantización inexistente. Reintentar con Q4_K_M.
                if self.req.quant != "Q4_K_M":
                    await self.emit({
                        "type": "log",
                        "level": "warn",
                        "text": f"{e} — fallback a Q4_K_M",
                    })
                    self.req.quant = "Q4_K_M"
                    await model_manager.ensure_gguf(model, self.req.quant, progress=model_progress)
                else:
                    raise
        gguf_path = model_manager.gguf_path(model, self.req.quant)
        await self.emit({"type": "log", "level": "success", "text": f"Modelo: {gguf_path.name}"})

        # 3. Motor: reusar si está corriendo CON el mismo modelo+quant; si no, reiniciar
        st = native_runtime.status("llamacpp")
        loaded = native_runtime.get_loaded("llamacpp")
        same_model = (
            loaded is not None
            and loaded.get("model") == self.req.model
            and loaded.get("quant") == self.req.quant
        )
        if st.state == "running" and not same_model:
            await self.emit({
                "type": "log",
                "level": "info",
                "text": (
                    f"Reiniciando motor: cargado={loaded or 'desconocido'} "
                    f"→ pedido={self.req.model}/{self.req.quant}"
                ),
            })
            native_runtime.stop("llamacpp")
            st = native_runtime.status("llamacpp")

        if st.state == "running" and same_model:
            await self.emit({
                "type": "log",
                "level": "info",
                "text": f"Reusando motor con {loaded['model']}/{loaded['quant']}",
            })
        else:
            # Calcular config óptima a partir de hardware + modelo
            optimal = get_optimal_config("llamacpp", model.id, self.hw)
            ctx = optimal.context_len if optimal.feasible else 4096
            kv = optimal.kv_cache or "f16"
            moe = optimal.moe_offload

            args = [
                "--host", "0.0.0.0",
                "--port", "8080",
                "-m", str(gguf_path),
                "--alias", model.id,  # nombre que /v1/chat/completions aceptará
                "-c", str(ctx),
                "-ngl", "99",
                "-ctk", kv, "-ctv", kv,
            ]
            if moe:
                args += ["--n-cpu-moe", str(moe)]
            # En llama.cpp moderno -fa requiere valor (on|off|auto)
            if optimal.flags.get("flashAttn"):
                args += ["-fa", "on"]
            if optimal.flags.get("mlock"):
                args += ["--mlock"]

            await self.emit({"type": "engine.start", "binary": str(binary), "args": args})
            native_runtime.start("llamacpp", exe=binary, args=args, port=8080)
            native_runtime.set_loaded(
                "llamacpp",
                {"model": model.id, "quant": self.req.quant, "ctx": ctx, "kv": kv},
            )
            self._owns_engine = True

            await self.emit({"type": "log", "level": "info", "text": "Esperando motor listo…"})
            await _wait_engine_ready(self.base_url, timeout=120.0)
            await self.emit({"type": "engine.ready", "base_url": self.base_url})

    async def _run_one(self, prompt: Prompt, headers: dict[str, str]) -> None:
        await self.emit({
            "type": "phase",
            "model": self.req.model,
            "prompt": prompt.id,
            "phase": "load",
        })
        await self.emit({"type": "phase", "phase": "warmup"})

        if not self.base_url:
            err = f"No base_url para motor {self.req.engine}"
            await self.emit({"type": "log", "level": "error", "text": err})
            self._record_error(prompt, err)
            return

        # Para motores OpenAI-compatible locales el `model` que pasamos en el body suele
        # ignorarse (sirve cualquier valor). Para APIs cloud, usamos el model_id directamente.
        model_for_engine = self.req.model

        t0 = time.perf_counter()
        ttft_ms: int | None = None
        text_chunks: list[str] = []
        token_count = 0
        ram_peak = psutil.virtual_memory().used / (1024**3)
        vram_peak = _get_vram_used_gb()
        error = ""

        try:
            async for kind, data in _stream_openai_chat(
                self.base_url, model_for_engine, prompt, self.req.sampling, headers
            ):
                now = time.perf_counter()
                if kind == "first_token":
                    ttft_ms = int((now - t0) * 1000)
                    await self.emit({"type": "phase", "phase": "ttft", "ttft_ms": ttft_ms})
                    await self.emit({"type": "phase", "phase": "generate"})
                    text_chunks.append(data)
                    token_count += 1
                elif kind == "token":
                    text_chunks.append(data)
                    token_count += 1
                    if token_count % 8 == 0:
                        elapsed = now - t0 - (ttft_ms or 0) / 1000.0
                        tps_now = token_count / elapsed if elapsed > 0 else 0.0
                        await self.emit({
                            "type": "tokens",
                            "current": token_count,
                            "target": prompt.target_tokens,
                            "tps_current": round(tps_now, 2),
                        })
                        ram_peak = max(ram_peak, psutil.virtual_memory().used / (1024**3))
                        vram_peak = max(vram_peak, _get_vram_used_gb())
                elif kind == "done":
                    break
        except Exception as e:
            error = str(e)
            await self.emit({"type": "log", "level": "error", "text": f"{prompt.id}: {error}"})

        elapsed_total = time.perf_counter() - t0
        gen_time = elapsed_total - (ttft_ms or 0) / 1000.0
        tps = token_count / gen_time if gen_time > 0 else 0.0
        output = "".join(text_chunks)
        quality = _quality_heuristic(output, prompt.reference)

        await self.emit({"type": "phase", "phase": "quality", "score": quality})

        result = ResultPayload(
            model_id=self.req.model,
            prompt_id=prompt.id,
            tps=round(tps, 2),
            ttft_ms=ttft_ms or 0,
            vram_gb=round(vram_peak, 2),
            ram_gb=round(ram_peak, 2),
            quality=quality,
            cost=0.0,
            ctx_used=token_count,
            raw_output=output[:4000],
            error=error,
        )
        self.results.append(result)
        await self.emit({"type": "result", "result": result.model_dump()})

    def _record_error(self, prompt: Prompt, err: str) -> None:
        self.results.append(
            ResultPayload(
                model_id=self.req.model,
                prompt_id=prompt.id,
                tps=0.0,
                ttft_ms=0,
                vram_gb=0.0,
                ram_gb=0.0,
                quality=0.0,
                cost=0.0,
                ctx_used=0,
                raw_output="",
                error=err,
            )
        )

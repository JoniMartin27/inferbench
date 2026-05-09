"""Ejecución real de benchmarks contra motores OpenAI-compatibles + SSE eventing."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import psutil
from loguru import logger
from pydantic import BaseModel, Field

from .hardware import detect_hardware

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


# Default base URLs por motor local (asumen contenedores corriendo en localhost)
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


class BenchmarkRequest(BaseModel):
    engine: str
    model: str
    prompts: list[str] = Field(default_factory=lambda: ["reasoning", "code", "summary", "chat"])
    base_url: str | None = None
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
    """Heurística MVP: 0-100 según longitud no vacía + overlap simple con referencia.
    Para el M4 esto es suficiente; M8/M9 puede sustituir con LLM-judge.
    """
    if not output.strip():
        return 0.0
    base = min(60.0, len(output) / 8.0)  # premia respuestas con sustancia
    if ref:
        ref_words = {w.lower() for w in ref.split() if len(w) > 3}
        if ref_words:
            out_words = {w.lower() for w in output.split() if len(w) > 3}
            overlap = len(ref_words & out_words) / len(ref_words)
            base += overlap * 40.0
    return min(100.0, round(base, 1))


async def _stream_openai_chat(
    base_url: str,
    model: str,
    prompt: Prompt,
    sampling: dict[str, Any],
    headers: dict[str, str],
) -> AsyncIterator[tuple[str, Any]]:
    """Cede tuples (kind, data). kind ∈ {"first_token", "token", "done"}.

    Usa formato OpenAI-compatible /v1/chat/completions con stream=true.
    """
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    body = {
        "model": model,
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
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        async with client.stream("POST", url, json=body, headers=headers) as resp:
            if resp.status_code >= 400:
                text = await resp.aread()
                raise RuntimeError(f"HTTP {resp.status_code}: {text.decode(errors='replace')[:500]}")
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


class BenchmarkRunner:
    """Orquesta una corrida: emite eventos vía asyncio.Queue."""

    def __init__(self, req: BenchmarkRequest):
        self.req = req
        self.run_id = uuid.uuid4().hex[:12]
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.results: list[ResultPayload] = []
        self.hw = detect_hardware()
        self.base_url = req.base_url or DEFAULT_BASE_URLS.get(req.engine)

    async def emit(self, evt: dict[str, Any]) -> None:
        await self.queue.put(evt)

    async def run(self) -> None:
        try:
            prompts = [p for p in (get_prompt(pid) for pid in self.req.prompts) if p]
            await self.emit({"type": "start", "run_id": self.run_id, "total": len(prompts)})

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
            await self.queue.put({"type": "_eof"})

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

        t0 = time.perf_counter()
        ttft_ms: int | None = None
        text_chunks: list[str] = []
        token_count = 0
        ram_peak = psutil.virtual_memory().used / (1024**3)
        vram_peak = _get_vram_used_gb()
        error = ""

        try:
            async for kind, data in _stream_openai_chat(
                self.base_url, self.req.model, prompt, self.req.sampling, headers
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

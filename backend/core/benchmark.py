"""Ejecución automática de benchmarks: bootstrap (binario+modelo+motor) → benchmark → teardown.

El modelo se obtiene de:
- `local_path` del request si está presente (GGUF local descubierto)
- caché local (si ya se descargó antes)
- HuggingFace (si el modelo del catálogo tiene `hf_gguf`)


Eventos SSE emitidos:
  start, log, phase
  engine.install (con pct), model.download (con pct), engine.start, engine.ready
  phase (load|warmup|ttft|generate|quality), tokens, result, done
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import psutil
from loguru import logger
from pydantic import BaseModel, Field

from . import binary_manager, docker_mgr, model_manager, native_runtime, ollama_manager
from .hardware import detect_hardware
from .models_catalog import get_model
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
    engine_opts: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""
    local_path: str | None = None  # ruta directa a un GGUF local (salta descarga HF)
    # Evaluación de calidad. mode: "heuristic" (default) | "self" (el motor local se
    # autoevalúa) | "api" (juez OpenAI-compatible externo). Para "api": base_url, model, api_key.
    judge: dict[str, Any] = Field(default_factory=dict)


def _extra_engine_args_static(opts: dict[str, Any]) -> list[str]:
    """Construye flags llama-server adicionales desde un dict de overrides."""
    extra: list[str] = []
    if opts.get("noMmap") is True:
        extra += ["--no-mmap"]
    if opts.get("mlock") is True:
        extra += ["--mlock"]
    if "flashAttn" in opts:
        v = opts["flashAttn"]
        extra += ["-fa", "on" if v else "off"]
    if "threads" in opts:
        extra += ["-t", str(int(opts["threads"]))]
    if "batchSize" in opts:
        extra += ["--batch-size", str(int(opts["batchSize"]))]
    if "ubatchSize" in opts:
        extra += ["--ubatch-size", str(int(opts["ubatchSize"]))]
    if "cacheReuse" in opts:
        extra += ["--cache-reuse", str(int(opts["cacheReuse"]))]
    if opts.get("nkvo") is True:
        extra += ["--no-kv-offload"]
    if opts.get("swaFull") is True:
        extra += ["--swa-full"]
    return extra


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


# --- Scorer de calidad offline (Python puro, sin GPU/modelo/red: corre en cualquier PC) ---
# Basado en la respuesta de referencia: F1 de tokens recall-weighted + recall exacto de
# números (crítico en mates/razonamiento) + penalización de texto degenerado. Es la opción
# por defecto porque funciona en todo tipo de ordenadores; el LLM-judge es la mejora opcional.

_QUALITY_STOP = {
    "de", "la", "el", "en", "y", "a", "los", "las", "un", "una", "que", "es", "por",
    "con", "para", "su", "se", "del", "al", "lo", "como", "más", "o", "pero", "sus",
    "le", "ya", "este", "esta", "son", "cada", "paga", "total",
    "the", "a", "an", "of", "to", "and", "in", "is", "for", "on", "with", "as", "by",
    "that", "this", "are", "be", "it", "or", "from", "at",
}


def _q_tokens(text: str) -> list[str]:
    text = re.sub(r"[^\w\s.%+-]", " ", text.lower(), flags=re.UNICODE)
    return [t for t in text.split() if t]


def _q_content(toks: list[str]) -> list[str]:
    # Stem por prefijo (6 chars): casa inflexiones ES/EN sin dependencias
    # (energía/energético, regula/regulación, genera/generan). Números intactos.
    out = []
    for t in toks:
        if t in _QUALITY_STOP or not (len(t) > 2 or t.isdigit()):
            continue
        out.append(t if t.isdigit() else t[:6])
    return out


def _q_numbers(text: str) -> set[str]:
    out = set()
    for r in re.findall(r"\d[\d.,]*", text):
        digits = r.rstrip(".,").replace(".", "").replace(",", "")
        if digits:
            out.add(digits)
    return out


def _q_repetition_penalty(toks: list[str]) -> float:
    if len(toks) < 12:
        return 1.0
    bg = list(zip(toks, toks[1:]))
    if not bg:
        return 1.0
    uniq = len(set(bg)) / len(bg)
    return 1.0 if uniq >= 0.6 else max(0.3, uniq / 0.6)


def _q_fbeta(p: float, r: float, beta: float = 2.0) -> float:
    b2 = beta * beta
    denom = b2 * p + r
    return (1 + b2) * p * r / denom if denom > 0 else 0.0


def _quality_heuristic(output: str, ref: str) -> float:
    """Calidad 0-100 offline. Con referencia: cobertura de datos clave (F1 recall-weighted
    + números). Sin referencia: proxy por longitud y no-degeneración (cap 70, no afirma
    corrección). Para juicio fiable de tareas abiertas, usar el LLM-judge."""
    out = output.strip()
    if not out:
        return 0.0
    out_toks = _q_tokens(out)
    rep = _q_repetition_penalty(out_toks)

    if not ref.strip():
        # Sin referencia no se puede medir corrección sin un LLM: proxy honesto.
        return round(min(70.0, 70.0 * min(1.0, len(out) / 300.0)) * rep, 1)

    out_c, ref_c = _q_content(out_toks), _q_content(_q_tokens(ref))
    out_set, ref_set = set(out_c), set(ref_c)
    overlap = out_set & ref_set
    recall = len(overlap) / len(ref_set) if ref_set else 0.0
    precision = len(overlap) / len(out_set) if out_set else 0.0
    f = _q_fbeta(precision, recall, beta=2.0)

    bg_ref = set(zip(ref_c, ref_c[1:]))
    bg_recall = len(set(zip(out_c, out_c[1:])) & bg_ref) / len(bg_ref) if bg_ref else 0.0

    ref_nums = _q_numbers(ref)
    if ref_nums:
        num_recall = len(ref_nums & _q_numbers(out)) / len(ref_nums)
        base = 0.5 * num_recall + 0.35 * f + 0.15 * bg_recall
    else:
        base = 0.8 * f + 0.2 * bg_recall

    return round(min(100.0, 100.0 * base * rep), 1)


# Rúbrica en inglés y en un único mensaje de usuario (sin `system`): probado contra
# modelos pequeños (incluso 1B), este formato QUESTION/ANSWER + "Return only the score
# as a number from 0 to 100" es el que discrimina de forma fiable bien/mal. Meter la
# instrucción en `system` o reformularla hacía que modelos débiles colapsaran a 0.
def _build_judge_user(prompt: Prompt, output: str) -> str:
    parts = [
        "You are grading an AI assistant answer. Give an integer quality score from "
        "0 (terrible, empty or wrong) to 100 (perfect: correct, complete and relevant). "
        "Be strict and penalize hallucinations and incompleteness.",
        f"QUESTION: {prompt.prompt.strip()}",
    ]
    if prompt.reference:
        parts.append(f"REFERENCE (a guide, not literal): {prompt.reference.strip()}")
    parts.append(f"ANSWER: {output.strip()[:6000]}")
    parts.append("Return only the score as a number from 0 to 100:")
    return "\n".join(parts)


def _parse_judge_score(content: str) -> float | None:
    """Primer entero en rango 0-100 de la respuesta del juez (robusto ante texto extra)."""
    for tok in re.findall(r"\d{1,3}", content or ""):
        n = int(tok)
        if 0 <= n <= 100:
            return float(n)
    return None


async def _llm_judge_score(
    prompt: Prompt,
    output: str,
    base_url: str,
    model: str,
    headers: dict[str, str],
) -> float | None:
    """Pide a un LLM-juez (endpoint OpenAI-compatible) que puntúe la respuesta 0-100.

    Devuelve el score o None si falla / no devuelve número (el llamador cae a la heurística).
    """
    if not output.strip():
        return 0.0
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": _build_judge_user(prompt, output)}],
        "max_tokens": 16,
        "temperature": 0.0,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0)) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    except Exception as e:
        logger.warning(f"LLM-judge falló: {e}")
        return None
    return _parse_judge_score(content)


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
        self._owns_engine = False
        self.cancelled = asyncio.Event()

    def cancel(self) -> None:
        self.cancelled.set()

    def _extra_engine_args(self, opts: dict[str, Any]) -> list[str]:
        return _extra_engine_args_static(opts)

    async def emit(self, evt: dict[str, Any]) -> None:
        await self.queue.put(evt)

    async def run(self) -> None:
        try:
            prompts = [p for p in (get_prompt(pid) for pid in self.req.prompts) if p]
            await self.emit({"type": "start", "run_id": self.run_id, "total": len(prompts)})

            if self.req.auto and not self.is_api:
                try:
                    await self._bootstrap()
                except asyncio.CancelledError:
                    await self.emit({"type": "log", "level": "warn",
                                     "text": "Descarga/instalación cancelada por el usuario"})
                    await self.emit({"type": "done", "run_id": self.run_id, "cancelled": True})
                    return
                except Exception as e:
                    logger.exception("bootstrap failed")
                    await self.emit({"type": "log", "level": "error", "text": f"Bootstrap: {e}"})
                    await self.emit({"type": "done", "run_id": self.run_id, "error": str(e)})
                    return

            if self.cancelled.is_set():
                await self.emit({"type": "log", "level": "warn", "text": "Cancelado antes de iniciar"})
                await self.emit({"type": "done", "run_id": self.run_id, "cancelled": True})
                return

            headers = {"Content-Type": "application/json"}
            if self.req.api_key:
                headers["Authorization"] = f"Bearer {self.req.api_key}"

            for prompt in prompts:
                if self.cancelled.is_set():
                    await self.emit({"type": "log", "level": "warn", "text": "Benchmark cancelado"})
                    break
                await self._run_one(prompt, headers)

            await self.emit({
                "type": "done",
                "run_id": self.run_id,
                "cancelled": self.cancelled.is_set(),
            })
        except Exception as e:
            logger.exception("benchmark failed")
            await self.emit({"type": "log", "level": "error", "text": f"Fatal: {e}"})
            await self.emit({"type": "done", "run_id": self.run_id, "error": str(e)})
        finally:
            if self._owns_engine and (not self.req.keep_alive or self.cancelled.is_set()):
                try:
                    await self.emit({"type": "log", "level": "info", "text": "Deteniendo motor…"})
                    native_runtime.stop(self.req.engine)
                except Exception:
                    pass
            await self.queue.put({"type": "_eof"})

    async def _bootstrap(self) -> None:
        """Asegura: binario/imagen + modelo + motor corriendo. Dispatcha por motor."""
        if self.req.engine == "llamacpp":
            await self._bootstrap_llamacpp()
        elif self.req.engine == "ollama":
            await self._bootstrap_ollama()
        elif self.req.engine in ("vllm", "sglang", "tgi"):
            await self._bootstrap_docker_engine()
        else:
            raise RuntimeError(f"Bootstrap no soportado para motor: {self.req.engine}")

    async def _bootstrap_ollama(self) -> None:
        """Asegura Ollama instalado, daemon corriendo, modelo descargado."""
        if not ollama_manager.is_installed():
            url = ollama_manager.installer_url() or "https://ollama.com/download"
            raise RuntimeError(
                f"Ollama no instalado. Descárgalo desde {url} y vuelve a intentarlo."
            )

        # Daemon
        if not await ollama_manager.is_running():
            await self.emit({"type": "log", "level": "info", "text": "Arrancando Ollama daemon…"})
            await ollama_manager.ensure_running(timeout=30.0)
            await self.emit({"type": "log", "level": "success", "text": "Ollama daemon corriendo"})
        else:
            await self.emit({"type": "log", "level": "info", "text": "Reusando Ollama ya corriendo"})

        # Modelo
        model = get_model(self.req.model)
        tag = (model and model.ollama_tag) or self.req.model
        if not tag or ":" not in tag and not (model and model.ollama_tag):
            raise RuntimeError(
                f"No hay tag Ollama para {self.req.model}. Usa un tag tipo 'llama3.2:1b'."
            )

        if not await ollama_manager.has_model(tag):
            await self.emit({"type": "log", "level": "info", "text": f"Descargando modelo Ollama: {tag}"})

            async def progress(evt):
                await self.emit({"type": "model.download", **evt})

            await ollama_manager.pull_model(tag, progress=progress, cancel_event=self.cancelled)
            await self.emit({"type": "log", "level": "success", "text": f"Modelo listo: {tag}"})
        else:
            await self.emit({"type": "log", "level": "info", "text": f"Modelo ya descargado: {tag}"})

        # Reescribir el campo model con el tag para que /v1/chat/completions lo acepte
        self.req.model = tag
        self.base_url = ollama_manager.OLLAMA_BASE_URL
        await self.emit({"type": "engine.ready", "base_url": self.base_url})

    async def _bootstrap_docker_engine(self) -> None:
        """Arranca vLLM/SGLang/TGI vía Docker, con HF model id."""
        from engines import registry

        engine = registry.get_engine(self.req.engine)
        port = self.meta_port = engine.meta.default_port

        d = docker_mgr.availability()
        if not d.get("available"):
            raise RuntimeError(
                f"Docker no disponible: {d.get('reason', '')}. "
                f"Necesario para {self.req.engine}. Arranca Docker Desktop."
            )

        model = get_model(self.req.model)
        hf_id = (model and model.hf_repo) or self.req.model
        if not hf_id:
            raise RuntimeError(f"No hay HF repo para {self.req.model}")

        # Si ya está corriendo el contenedor con el mismo modelo, reusa
        loaded = native_runtime.get_loaded(self.req.engine)
        st = engine.status()
        if st and st.state == "running" and loaded and loaded.get("model") == hf_id:
            await self.emit({
                "type": "log",
                "level": "info",
                "text": f"Reusando {self.req.engine} con {hf_id}",
            })
        else:
            if st and st.state == "running":
                await self.emit({"type": "log", "level": "info", "text": "Reiniciando contenedor…"})
                engine.stop()

            from engines.base import StartRequest as EngineStartRequest

            ereq = EngineStartRequest(
                runtime="docker",
                gpu=True,
                engine_opts={
                    "hf_model_id": hf_id,
                    "contextLen": self.req.engine_opts.get("contextLen") or 4096,
                    "quant": self.req.quant if self.req.quant.lower() != "q4_k_m" else None,
                    **self.req.engine_opts,
                },
            )
            await self.emit({
                "type": "log",
                "level": "info",
                "text": f"Arrancando contenedor {engine.meta.image} con modelo {hf_id}…",
            })
            await self.emit({"type": "engine.start", "binary": engine.meta.image, "args": engine.build_command(ereq)})
            await engine.start(ereq)
            native_runtime.set_loaded(
                self.req.engine,
                {"model": hf_id, "quant": self.req.quant},
            )
            self._owns_engine = True

        self.base_url = f"http://localhost:{port}"
        # Para vLLM y similares, el field "model" en el request DEBE ser el hf_id
        self.req.model = hf_id

        await self.emit({"type": "log", "level": "info", "text": "Esperando motor listo (puede tardar varios minutos en primer arranque)…"})
        await _wait_engine_ready(self.base_url, timeout=600.0)
        await self.emit({"type": "engine.ready", "base_url": self.base_url})

    async def _bootstrap_llamacpp(self) -> None:
        """Asegura: binario nativo + modelo GGUF + motor corriendo."""
        model = get_model(self.req.model)
        if model is None:
            raise RuntimeError(f"Modelo desconocido: {self.req.model}")

        # 1. Binario nativo + DLLs CUDA si aplica
        # install_llamacpp es idempotente: descarga solo lo que falte (binario y/o cudart)
        async def bin_progress(evt):
            await self.emit({"type": "engine.install", **evt})

        if not binary_manager.llamacpp_fully_installed():
            await self.emit({"type": "log", "level": "info", "text": "Preparando llama.cpp…"})
            await binary_manager.install_llamacpp(progress=bin_progress, cancel_event=self.cancelled)
            await self.emit({"type": "log", "level": "success", "text": "Binario listo"})
        binary = binary_manager.llamacpp_binary_path()

        # 2. Modelo GGUF — opción A: ruta local explícita
        if self.req.local_path:
            local = Path(self.req.local_path)
            if not local.exists():
                raise RuntimeError(f"Ruta local no existe: {local}")
            gguf_path = local
            await self.emit({"type": "log", "level": "success", "text": f"Modelo local: {local.name}"})
            # Saltamos directamente al paso 3
            await self._start_engine_with_path(model, gguf_path, binary)
            return
        # Opción B: descarga desde HF
        if not model.hf_gguf:
            raise RuntimeError(
                f"El modelo {model.id} no tiene fuente HF GGUF. Selecciona otro o pasa local_path/base_url."
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
                await model_manager.ensure_gguf(model, self.req.quant, progress=model_progress,
                                                cancel_event=self.cancelled)
            except RuntimeError as e:
                # Probable: cuantización inexistente. Reintentar con Q4_K_M.
                if self.req.quant != "Q4_K_M":
                    await self.emit({
                        "type": "log",
                        "level": "warn",
                        "text": f"{e} — fallback a Q4_K_M",
                    })
                    self.req.quant = "Q4_K_M"
                    await model_manager.ensure_gguf(model, self.req.quant, progress=model_progress,
                                                    cancel_event=self.cancelled)
                else:
                    raise
        gguf_path = model_manager.gguf_path(model, self.req.quant)
        await self.emit({"type": "log", "level": "success", "text": f"Modelo: {gguf_path.name}"})

        await self._start_engine_with_path(model, gguf_path, binary)

    async def _start_engine_with_path(self, model, gguf_path, binary):
        """Arranca llama-server con el GGUF dado (ruta local) si no está ya corriendo."""
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

            n_threads = max(2, (psutil.cpu_count(logical=False) or 4))
            ngl = optimal.flags.get("ngl", 99) if optimal.feasible else 99
            # Permitir overrides de KV K/V independientes desde engine_opts
            req_opts = self.req.engine_opts or {}
            kv_k = req_opts.get("kvCacheK") or req_opts.get("kvCache") or kv
            kv_v = req_opts.get("kvCacheV") or req_opts.get("kvCache") or kv
            args = [
                "--host", "0.0.0.0",
                "--port", "8080",
                "-m", str(gguf_path),
                "--alias", model.id,
                "-c", str(ctx),
                "-ngl", str(ngl),
                "-ctk", kv_k, "-ctv", kv_v,
                "-t", str(n_threads),
                "--batch-size", "2048",
                "--ubatch-size", "512",
            ]
            if moe:
                args += ["--n-cpu-moe", str(moe)]
            if optimal.flags.get("flashAttn"):
                args += ["-fa", "on"]
            if optimal.flags.get("mlock"):
                args += ["--mlock"]
            if optimal.flags.get("noMmap"):
                args += ["--no-mmap"]
            if optimal.flags.get("cacheReuse"):
                args += ["--cache-reuse", str(int(optimal.flags["cacheReuse"]))]
            if self.req.engine_opts:
                args += self._extra_engine_args(self.req.engine_opts)

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
                if self.cancelled.is_set():
                    break
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

        if self.cancelled.is_set() and not error:
            error = "cancelado"

        elapsed_total = time.perf_counter() - t0
        gen_time = elapsed_total - (ttft_ms or 0) / 1000.0
        tps = token_count / gen_time if gen_time > 0 else 0.0
        output = "".join(text_chunks)

        quality = _quality_heuristic(output, prompt.reference)
        method = "heuristic"
        judge_mode = (self.req.judge or {}).get("mode", "heuristic")
        if judge_mode in ("self", "api") and output.strip() and not error:
            j_url, j_model, j_headers = self._resolve_judge(headers, model_for_engine)
            if j_url and j_model:
                await self.emit({"type": "phase", "phase": "judging"})
                score = await _llm_judge_score(prompt, output, j_url, j_model, j_headers)
                if score is not None:
                    quality = score
                    method = f"llm:{judge_mode}"
                else:
                    await self.emit({
                        "type": "log", "level": "warn",
                        "text": f"{prompt.id}: LLM-judge no respondió, uso heurística",
                    })

        await self.emit({"type": "phase", "phase": "quality", "score": quality, "method": method})

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

    def _resolve_judge(
        self, engine_headers: dict[str, str], model_for_engine: str
    ) -> tuple[str | None, str | None, dict[str, str]]:
        """Devuelve (base_url, model, headers) del juez según req.judge."""
        j = self.req.judge or {}
        mode = j.get("mode", "heuristic")
        if mode == "self":
            # El propio motor local se autoevalúa (offline, sin coste).
            return self.base_url, model_for_engine, engine_headers
        if mode == "api":
            j_engine = j.get("engine")
            base_url = j.get("base_url") or DEFAULT_BASE_URLS.get(j_engine or "")
            model = j.get("model")
            headers = {"Content-Type": "application/json"}
            key = j.get("api_key")
            if key:
                headers["Authorization"] = f"Bearer {key}"
            return base_url, model, headers
        return None, None, engine_headers

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

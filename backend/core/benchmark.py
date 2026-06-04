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
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import psutil
from loguru import logger
from pydantic import BaseModel, Field, field_validator

from . import (
    binary_manager,
    compat,
    docker_mgr,
    model_manager,
    native_runtime,
    ollama_manager,
    secrets,
)
from .hardware import detect_hardware, gpu_used_gb
from .models_catalog import get_model
from .optimizer import _estimate_moe_offload, get_optimal_config, plan_llamacpp_run

PROMPTS_FILE = Path(__file__).resolve().parent.parent / "data" / "prompts.json"


class Prompt(BaseModel):
    id: str
    name: str
    type: str
    system: str = ""
    prompt: str
    target_tokens: int = 256
    reference: str = ""
    image: str | None = None  # filename (relativo a data/) de una imagen → prompt multimodal
    # Checklist de atributos verificables: lista de grupos de sinónimos. La calidad es la
    # fracción de grupos que aparecen en la respuesta. Útil para visión (ground-truth de la
    # imagen) y para cualquier tarea con hechos comprobables. Tiene prioridad sobre reference.
    keywords: list[list[str]] | None = None
    # Casos de prueba (aserciones Python) que se ejecutan contra el código del modelo. La
    # calidad es el % de casos que pasan. Mide si el código FUNCIONA, no su parecido textual.
    code_tests: list[str] | None = None
    # Fichero (en data/) con un contexto largo que se antepone al prompt. Para tests de
    # contexto largo / recuperación (needle-in-haystack) que estresan la ventana de contexto.
    context_file: str | None = None


def _prompt_user_text(prompt: Prompt) -> str:
    """Texto de usuario efectivo: si el prompt referencia un `context_file`, antepone su
    contenido (test de contexto largo). Si no, el prompt tal cual."""
    if not prompt.context_file:
        return prompt.prompt
    path = PROMPTS_FILE.parent / prompt.context_file
    try:
        return f"{path.read_text(encoding='utf-8')}\n\n{prompt.prompt}"
    except OSError:
        return prompt.prompt


def _image_b64(image: str) -> tuple[str, str]:
    """Devuelve (media_type, base64) de una imagen del directorio data/."""
    import base64
    import mimetypes

    path = image if Path(image).is_absolute() else str(PROMPTS_FILE.parent / image)
    mime = mimetypes.guess_type(path)[0] or "image/png"
    return mime, base64.b64encode(Path(path).read_bytes()).decode("ascii")


def _image_data_url(image: str) -> str:
    """Data URL base64 de una imagen del directorio data/ (formato OpenAI vision)."""
    mime, b64 = _image_b64(image)
    return f"data:{mime};base64,{b64}"


def _find_local_mmproj(folder: Path) -> Path | None:
    """Busca un GGUF de tipo mmproj (projector de visión) en la misma carpeta."""
    try:
        for f in sorted(folder.glob("*.gguf")):
            if "mmproj" in f.name.lower():
                return f
    except OSError:
        pass
    return None


def _build_chat_body(model_id_for_engine: str, prompt: Prompt, sampling: dict[str, Any]) -> dict:
    """Construye el body de /v1/chat/completions. Si el prompt lleva imagen, el content
    del usuario es un array texto+imagen (formato OpenAI vision, que llama-server acepta
    arrancado con --mmproj). Extraído para poder testearlo sin red."""
    text = _prompt_user_text(prompt)
    if prompt.image:
        user_content: Any = [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": _image_data_url(prompt.image)}},
        ]
    else:
        user_content = text
    messages = [
        {"role": "system", "content": prompt.system} if prompt.system else None,
        {"role": "user", "content": user_content},
    ]
    return {
        "model": model_id_for_engine,
        "messages": [m for m in messages if m],
        "max_tokens": prompt.target_tokens,
        "stream": True,
        **sampling,
    }


@lru_cache(maxsize=1)
def load_prompts() -> list[Prompt]:
    raw = json.loads(PROMPTS_FILE.read_text(encoding="utf-8"))
    return [Prompt.model_validate(p) for p in raw]


def get_prompt(prompt_id: str) -> Prompt | None:
    for p in load_prompts():
        if p.id == prompt_id:
            return p
    return None


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_ALLOWED_CLOUD_HOSTS = {
    "api.openai.com", "api.anthropic.com", "openrouter.ai",
    "integrate.api.nvidia.com",
}


def _validate_base_url(url: str | None) -> None:
    """Rechaza base_url que apunte a hosts distintos de loopback o APIs cloud conocidas.

    Previene SSRF: un atacante con acceso local podría redirigir las peticiones (con el
    api_key en Authorization) a servicios de metadatos cloud (169.254.169.254) o a la
    red interna.
    """
    if url is None:
        return
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    if host in _LOOPBACK_HOSTS or host in _ALLOWED_CLOUD_HOSTS:
        return
    raise ValueError(
        f"base_url host '{host}' no permitido. "
        "Usa loopback (localhost/127.0.0.1) o una API cloud conocida."
    )


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


def supports_vision(engine: str, model: Any) -> bool:
    """¿Puede este (motor, modelo) procesar imágenes?

    - APIs cloud: sí (gpt-4o, claude… son multimodales; el usuario elige el modelo).
    - Locales (llama.cpp nativo, vLLM/SGLang/TGI Docker): si el modelo tiene tag `vision`
      (lleva mmproj en llama.cpp; vLLM/SGLang sirven el modelo de visión completo).
    """
    return engine in API_ENGINES or bool(model and getattr(model, "is_vision", False))


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

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, v):
        _validate_base_url(v)
        return v

    @field_validator("local_path")
    @classmethod
    def _check_local_path(cls, v):
        if v is None:
            return v
        if not v.lower().endswith(".gguf"):
            raise ValueError("local_path debe apuntar a un fichero .gguf")
        # Rechaza rutas UNC (\\host\share o //host/share) y bytes nulos: en Windows, abrir
        # una UNC a un host atacante filtra el hash NTLM del usuario. Solo rutas locales.
        if v.startswith("\\\\") or v.startswith("//") or "\x00" in v:
            raise ValueError("local_path no puede ser una ruta UNC ni contener bytes nulos")
        return v

    @field_validator("engine_opts")
    @classmethod
    def _check_engine_opts(cls, v):
        _KV_VALID = {"f16", "q8_0", "q4_0", "q4_1", "q5_0", "q5_1", "iq4_nl"}
        for key in ("kvCacheK", "kvCacheV", "kvCache"):
            val = v.get(key)
            if val is not None and val not in _KV_VALID:
                raise ValueError(f"engine_opts.{key}={val!r} inválido. Valores permitidos: {_KV_VALID}")
        _INT_BOUNDS = {
            "contextLen": (256, 131_072),
            "threads":    (1, 512),
            "batchSize":  (64, 32_768),
            "ubatchSize": (64, 8_192),
            "moeOffload": (0, 1_000),
            "cacheReuse": (0, 131_072),
        }
        for key, (lo, hi) in _INT_BOUNDS.items():
            val = v.get(key)
            if val is not None:
                try:
                    ival = int(val)
                except (TypeError, ValueError):
                    raise ValueError(f"engine_opts.{key} debe ser entero")
                if not (lo <= ival <= hi):
                    raise ValueError(f"engine_opts.{key}={ival} fuera de rango [{lo}, {hi}]")
        return v

    @field_validator("judge")
    @classmethod
    def _check_judge(cls, v):
        # Si el juez es una API externa, su base_url pasa por el MISMO allowlist anti-SSRF
        # que base_url (lleva la API key en Authorization). Rechazo temprano en el borde.
        if isinstance(v, dict) and v.get("mode") == "api":
            _validate_base_url(v.get("base_url"))
        return v


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


def _q_norm(s: str) -> str:
    """Minúsculas + sin diacríticos, para casar 'círculo'/'circulo' y ES/EN."""
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c)
    )


def _quality_keywords(output: str, groups: list[list[str]]) -> float:
    """Calidad 0-100 por checklist: fracción de grupos de sinónimos cuyo término aparece
    en la respuesta. Cada grupo es un atributo verificable (p.ej. un color o una forma de
    la imagen); basta con que el modelo mencione UNA de sus variantes.

    Casa por límite de palabra + prefijo (`\\bterm`): así "código" casa "códigos"/"codifica"
    (morfología) pero "500" NO casa dentro de "1500" (no inventa aciertos). Sin acentos, ES/EN.
    """
    if not groups:
        return 0.0
    low = _q_norm(output)
    hits = sum(
        1
        for group in groups
        if any(re.search(r"\b" + re.escape(_q_norm(term)), low) for term in group)
    )
    return round(hits / len(groups) * 100, 1)


def _extract_code(output: str) -> str:
    """Extrae el/los bloque(s) de código del output del modelo (fences markdown ```)."""
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", output, re.DOTALL | re.IGNORECASE)
    if blocks:
        return "\n\n".join(b.strip() for b in blocks)
    return output  # sin fences: probar el texto crudo (la prosa dará SyntaxError → 0)


async def _quality_code(output: str, tests: list[str], timeout: float = 10.0) -> float:
    """Calidad 0-100 EJECUTANDO el código del modelo contra casos de prueba reales.

    DESACTIVADO POR DEFECTO. Ejecutar output de un LLM en el host es peligroso aunque use
    `python -I`: el proceso tiene acceso completo al sistema de ficheros y la red. Solo se
    activa si INFERBENCH_CODE_EXEC=1 está presente en el entorno (opt-in explícito).
    Devuelve 0.0 sin ejecutar si la variable no está definida.
    """
    if not os.environ.get("INFERBENCH_CODE_EXEC"):
        return 0.0
    code = _extract_code(output)
    if not code.strip() or not tests:
        return 0.0
    runner = (
        code + "\n\n__tests = " + repr(list(tests)) + "\n"
        "__p = 0\n"
        "for __t in __tests:\n"
        "    try:\n"
        "        exec(__t, globals()); __p += 1\n"
        "    except Exception:\n"
        "        pass\n"
        "print('__RESULT__', __p, len(__tests))\n"
    )
    def _run() -> str:
        # subprocess.run en un HILO (vía asyncio.to_thread): no usa la maquinaria de
        # subprocesos del event loop, que falla en el SelectorEventLoop de Windows. Así el
        # scorer es robusto en cualquier loop. No bloquea el loop principal (corre en thread).
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            try:
                r = subprocess.run(
                    [sys.executable, "-I", "-c", runner], cwd=td,
                    capture_output=True, text=True, timeout=timeout,
                )
                return r.stdout
            except (subprocess.SubprocessError, OSError):
                return ""

    try:
        out = await asyncio.to_thread(_run)
    except Exception:
        return 0.0
    for line in reversed(out.splitlines()):
        if line.startswith("__RESULT__"):
            parts = line.split()
            if len(parts) == 3 and parts[2].isdigit() and int(parts[2]) > 0:
                return round(int(parts[1]) / int(parts[2]) * 100, 1)
    return 0.0


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
    body = _build_chat_body(model_id_for_engine, prompt, sampling)

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


def _build_anthropic_body(model_id: str, prompt: Prompt, sampling: dict[str, Any]) -> dict:
    """Body para la API NATIVA de Anthropic (/v1/messages): `system` va aparte (no como
    rol), `max_tokens` es obligatorio, y las imágenes son bloques {type:image, source:base64}.
    NO es OpenAI-compatible. Extraído para testearlo sin red."""
    text = _prompt_user_text(prompt)
    if prompt.image:
        mime, b64 = _image_b64(prompt.image)
        content: Any = [
            {"type": "text", "text": text},
            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
        ]
    else:
        content = text
    body: dict[str, Any] = {
        "model": model_id,
        "max_tokens": prompt.target_tokens,
        "messages": [{"role": "user", "content": content}],
        "stream": True,
    }
    if prompt.system:
        body["system"] = prompt.system
    for k in ("temperature", "top_p", "top_k"):  # Anthropic acepta este subconjunto
        if k in sampling:
            body[k] = sampling[k]
    return body


async def _stream_anthropic_chat(
    base_url: str,
    model_id_for_engine: str,
    prompt: Prompt,
    sampling: dict[str, Any],
    headers: dict[str, str],
) -> AsyncIterator[tuple[str, Any]]:
    """Streaming de la API nativa de Anthropic. Endpoint `/v1/messages`, auth `x-api-key`
    + `anthropic-version`, y eventos SSE distintos (content_block_delta.delta.text)."""
    url = f"{base_url.rstrip('/')}/v1/messages"
    body = _build_anthropic_body(model_id_for_engine, prompt, sampling)
    first = True
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
        async with client.stream("POST", url, json=body, headers=headers) as resp:
            if resp.status_code >= 400:
                text = await resp.aread()
                raise RuntimeError(f"HTTP {resp.status_code}: {text.decode(errors='replace')[:500]}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload:
                    continue
                try:
                    evt = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                etype = evt.get("type")
                if etype == "content_block_delta":
                    text = (evt.get("delta") or {}).get("text") or ""
                    if text:
                        if first:
                            yield ("first_token", text)
                            first = False
                        else:
                            yield ("token", text)
                elif etype == "error":
                    # Error a mitad de stream (rate limit, overloaded…). NO tragarlo:
                    # propagarlo para que el run se marque como error real, no como
                    # salida vacía atribuida erróneamente al modelo/KV.
                    msg = (evt.get("error") or {}).get("message") or "error desconocido"
                    raise RuntimeError(f"Anthropic stream error: {msg}")
                elif etype == "message_stop":
                    break
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
        # Acotada para no crecer sin límite si el cliente SSE se desconecta a
        # mitad de run. `emit` descarta el evento más viejo cuando está llena.
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2000)
        self.results: list[ResultPayload] = []
        self.hw = detect_hardware()
        self.is_api = req.engine in API_ENGINES
        self.base_url = req.base_url or DEFAULT_BASE_URLS.get(req.engine)
        self._owns_engine = False
        self.cancelled = asyncio.Event()

    def cancel(self) -> None:
        self.cancelled.set()

    async def emit(self, evt: dict[str, Any]) -> None:
        # Nunca bloquear al productor: si la cola está llena (consumidor SSE lento
        # o desconectado), descartamos el evento más viejo. Así el log en vivo
        # conserva siempre lo más reciente y el `_eof` final puede entregarse.
        if self.queue.full():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self.queue.put_nowait(evt)

    async def run(self) -> None:
        try:
            prompts = [p for p in (get_prompt(pid) for pid in self.req.prompts) if p]
            # Gating de visión: un prompt con imagen necesita un modelo multimodal (con
            # mmproj) en local. Para APIs lo dejamos pasar (gpt-4o etc. son multimodales).
            can_vision = supports_vision(self.req.engine, get_model(self.req.model))
            kept: list[Prompt] = []
            for p in prompts:
                if p.image and not can_vision:
                    await self.emit({"type": "log", "level": "warn",
                                     "text": f"Prompt '{p.id}' (imagen) omitido: "
                                             f"{self.req.model} no es un modelo de visión"})
                    continue
                kept.append(p)
            prompts = kept
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

            # APIs: si el request no trae key, usar la guardada en el keyring del SO.
            if self.is_api and not self.req.api_key:
                self.req.api_key = secrets.get_key(self.req.engine)

            headers = {"Content-Type": "application/json"}
            if self.req.api_key:
                if self.req.engine == "anthropic":  # API nativa: auth distinta a OpenAI
                    headers["x-api-key"] = self.req.api_key
                    headers["anthropic-version"] = "2023-06-01"
                else:
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
                    # engine.stop() cubre ambos runtimes: nativo (llamacpp/ollama) y Docker
                    # (vllm/sglang/tgi). Usar native_runtime.stop directamente dejaba el
                    # contenedor Docker corriendo y ocupando la GPU tras el benchmark.
                    from engines import registry

                    # stop() Docker es bloqueante (hasta ~10s); en un hilo para no congelar
                    # el event loop justo en la cancelación/teardown.
                    await asyncio.to_thread(registry.get_engine(self.req.engine).stop)
                    native_runtime.set_loaded(self.req.engine, None)
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
                await asyncio.to_thread(engine.stop)

            from engines.base import StartRequest as EngineStartRequest

            # La fracción de VRAM la fija y ACOTA cada motor en su build_command/
            # build_environment vía hardware.safe_gpu_fraction() (reserva margen para el
            # display → no satura la pantalla). Aquí solo pasamos lo que el usuario pidiera
            # explícitamente; el motor lo capa a lo seguro. El guard de _start_docker rechaza
            # el arranque si no cabe nada de forma segura.
            user_opts = dict(self.req.engine_opts)
            extra_env: dict[str, str] = {}

            ereq = EngineStartRequest(
                runtime="docker",
                gpu=True,
                extra_env=extra_env,
                engine_opts={
                    "hf_model_id": hf_id,
                    "contextLen": self.req.engine_opts.get("contextLen") or 4096,
                    # Los quants GGUF (Q8_0/Q4_K_M…) NO son métodos válidos de vLLM/SGLang/TGI.
                    # Solo se pasa si es un método que el motor entiende; si no, fp16 sin cuantizar.
                    "quant": (
                        self.req.quant
                        if self.req.quant.lower() in {"awq", "gptq", "fp8", "bitsandbytes", "eetq"}
                        else None
                    ),
                    **user_opts,
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
            # Visión: busca un mmproj hermano en la misma carpeta (no se descarga para locales)
            mmproj_local = _find_local_mmproj(local.parent)
            if model.is_vision and not mmproj_local:
                await self.emit({"type": "log", "level": "warn",
                                 "text": "Modelo de visión sin mmproj en la carpeta; correrá como texto"})
            await self._start_engine_with_path(model, gguf_path, binary, mmproj_local)
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

        # Visión: descarga el projector multimodal (mmproj) junto al modelo
        mmproj_path = await self._ensure_mmproj(model)

        await self._start_engine_with_path(model, gguf_path, binary, mmproj_path)

    async def _ensure_mmproj(self, model):
        """Descarga el mmproj (projector de visión) si el modelo lo necesita. Ruta o None.

        Falla suave: si la descarga del mmproj falla, se loguea y el modelo corre como
        texto (sin visión) en vez de abortar todo el benchmark.
        """
        if not (model and model.hf_gguf and model.hf_gguf.mmproj):
            return None
        if model_manager.mmproj_installed(model):
            return model_manager.mmproj_path(model)
        await self.emit({"type": "log", "level": "info",
                         "text": "Descargando projector de visión (mmproj)…"})

        async def mm_progress(evt):
            await self.emit({"type": "model.download", **evt})

        try:
            path = await model_manager.ensure_mmproj(
                model, progress=mm_progress, cancel_event=self.cancelled
            )
            if path:
                await self.emit({"type": "log", "level": "success",
                                 "text": f"mmproj listo: {path.name} (visión habilitada)"})
            return path
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self.emit({"type": "log", "level": "warn",
                             "text": f"mmproj falló ({e}); el modelo correrá como texto"})
            return None

    async def _start_engine_with_path(self, model, gguf_path, binary, mmproj_path=None):
        """Arranca llama-server con el GGUF dado (ruta local) si no está ya corriendo.

        `mmproj_path` (opcional): projector de visión → arranca con --mmproj.
        """
        # 3. Motor: reusar si está corriendo CON el mismo modelo+quant+mmproj; si no, reiniciar
        st = native_runtime.status("llamacpp")
        loaded = native_runtime.get_loaded("llamacpp")
        same_model = (
            loaded is not None
            and loaded.get("model") == self.req.model
            and loaded.get("quant") == self.req.quant
            and loaded.get("mmproj", False) == bool(mmproj_path)
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
            # Config base del optimizer (para flags/MoE heurísticos)…
            optimal = get_optimal_config("llamacpp", model.id, self.hw)
            snap = compat.HardwareSnapshot(vram_gb=self.hw.primary_vram_gb, ram_gb=self.hw.ram_gb)
            req_opts = self.req.engine_opts or {}

            # …pero ctx/ngl se calculan para el quant REAL y la KV efectiva que se corren
            # (no para el quant que el optimizer habría elegido). K y V pueden venir de un
            # preset de compresión del usuario (kvCacheK/kvCacheV) y nkvo = KV en RAM.
            kv_default = optimal.kv_cache or "f16"
            kv_k = req_opts.get("kvCacheK") or req_opts.get("kvCache") or kv_default
            kv_v = req_opts.get("kvCacheV") or req_opts.get("kvCache") or kv_default
            kv_in_ram = bool(req_opts.get("nkvo"))
            moe = optimal.moe_offload
            # El optimizer estimó el offload con Q4_K_M; recalcúlalo para el quant REAL que se
            # ejecuta (un Q8_0 ocupa ~2× y necesita descargar MÁS capas para no saturar la VRAM).
            if moe and model.is_moe:
                moe = _estimate_moe_offload(model, snap, self.req.quant) or moe

            ctx, ngl, ngl_mode = plan_llamacpp_run(
                model, snap, quant=self.req.quant, kv_k=kv_k, kv_v=kv_v,
                kv_in_ram=kv_in_ram, moe_offload=moe,
            )
            if req_opts.get("contextLen"):  # el contexto manual del usuario manda
                ctx = max(256, int(req_opts["contextLen"]))

            # Flags efectivas: base del optimizer, sobreescritas por engine_opts (sin duplicar).
            # KV cuantizada (≠ f16) REQUIERE flash attention en llama.cpp → forzar -fa on.
            kv_quantized = (kv_k != "f16") or (kv_v != "f16")
            fa = bool(req_opts.get("flashAttn", optimal.flags.get("flashAttn", True))) or kv_quantized
            mlock = bool(req_opts.get("mlock", optimal.flags.get("mlock", False)))
            no_mmap = bool(req_opts.get("noMmap", optimal.flags.get("noMmap", False)))
            cache_reuse = req_opts.get("cacheReuse", optimal.flags.get("cacheReuse"))
            n_threads = int(req_opts.get("threads", max(2, psutil.cpu_count(logical=False) or 4)))
            batch = int(req_opts.get("batchSize", 2048))
            ubatch = int(req_opts.get("ubatchSize", 512))

            await self.emit({
                "type": "log", "level": "info",
                "text": (f"Plan: quant={self.req.quant} ctx={ctx} ngl={ngl} ({ngl_mode}) "
                         f"KV={kv_k}/{kv_v}{' en RAM' if kv_in_ram else ''} "
                         f"fa={'on' if fa else 'off'}"),
            })

            args = [
                "--host", "0.0.0.0", "--port", "8080",
                "-m", str(gguf_path), "--alias", model.id,
                "-c", str(ctx), "-ngl", str(ngl),
                "-ctk", kv_k, "-ctv", kv_v,
                "-t", str(n_threads),
                "--batch-size", str(batch), "--ubatch-size", str(ubatch),
                "-fa", "on" if fa else "off",
            ]
            if mmproj_path:
                args += ["--mmproj", str(mmproj_path)]
            if moe:
                args += ["--n-cpu-moe", str(moe)]
            if mlock:
                args += ["--mlock"]
            if no_mmap:
                args += ["--no-mmap"]
            if cache_reuse:
                args += ["--cache-reuse", str(int(cache_reuse))]
            if kv_in_ram:
                args += ["--no-kv-offload"]
            if req_opts.get("swaFull"):
                args += ["--swa-full"]

            await self.emit({"type": "engine.start", "binary": str(binary), "args": args})
            native_runtime.start("llamacpp", exe=binary, args=args, port=8080)
            native_runtime.set_loaded(
                "llamacpp",
                {"model": model.id, "quant": self.req.quant, "ctx": ctx,
                 "kv": f"{kv_k}/{kv_v}", "mmproj": bool(mmproj_path)},
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
        vram_peak = gpu_used_gb()
        error = ""

        # Anthropic tiene API propia (no OpenAI-compatible); el resto van por /v1/chat/completions
        stream_fn = _stream_anthropic_chat if self.req.engine == "anthropic" else _stream_openai_chat
        try:
            async for kind, data in stream_fn(
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
                        # tok/s de generación: tokens TRAS el primero / tiempo TRAS el primero
                        # (el 1er token ya está contado, pero su tiempo es el TTFT, excluido aquí)
                        tps_now = (token_count - 1) / elapsed if elapsed > 0 and token_count > 1 else 0.0
                        await self.emit({
                            "type": "tokens",
                            "current": token_count,
                            "target": prompt.target_tokens,
                            "tps_current": round(tps_now, 2),
                        })
                        ram_peak = max(ram_peak, psutil.virtual_memory().used / (1024**3))
                        vram_peak = max(vram_peak, gpu_used_gb())
                elif kind == "done":
                    break
        except Exception as e:
            error = str(e)
            await self.emit({"type": "log", "level": "error", "text": f"{prompt.id}: {error}"})

        if self.cancelled.is_set() and not error:
            error = "cancelado"

        elapsed_total = time.perf_counter() - t0
        gen_time = elapsed_total - (ttft_ms or 0) / 1000.0
        # tok/s de generación = tokens generados TRAS el primero / tiempo TRAS el primero.
        # token_count incluye el 1er token, cuyo tiempo es el TTFT (ya excluido de gen_time);
        # contarlo en el numerador inflaba el tok/s en respuestas cortas (la métrica estrella).
        tps = (token_count - 1) / gen_time if gen_time > 0 and token_count > 1 else 0.0
        output = "".join(text_chunks)

        # Surfacing honesto: si el modelo no generó NADA y no hubo error/cancelación, suele
        # ser una KV demasiado agresiva (q4_0) que rompe la generación. No es un 0 silencioso.
        if not output.strip() and not error and not self.cancelled.is_set():
            error = "el modelo no generó tokens (¿KV demasiado comprimida para este modelo?)"
            await self.emit({"type": "log", "level": "warn", "text": f"{prompt.id}: {error}"})

        if prompt.code_tests and not os.environ.get("INFERBENCH_NO_CODE_EXEC"):
            # Ejecuta el código del modelo contra casos reales: mide si FUNCIONA.
            quality = await _quality_code(output, prompt.code_tests)
            method = "code-exec"
        elif prompt.keywords:
            # Checklist de atributos (p.ej. ground-truth de una imagen): mide corrección
            # de verdad, no solo solapamiento de tokens con una frase de referencia.
            quality = _quality_keywords(output, prompt.keywords)
            method = "checklist"
        else:
            quality = _quality_heuristic(output, prompt.reference)
            method = "heuristic"
        judge_mode = (self.req.judge or {}).get("mode", "heuristic")
        verifiable = bool(prompt.keywords or prompt.code_tests)
        # El LLM-judge solo aplica a prompts SIN scorer verificable (no a checklist/código).
        if not verifiable and judge_mode in ("self", "api") and output.strip() and not error:
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
            # Mismo allowlist anti-SSRF que el base_url principal: el juez también lleva la
            # API key del keyring en Authorization, así que su URL NO puede apuntar a
            # metadatos cloud (169.254.169.254) ni a la red interna.
            _validate_base_url(base_url)
            model = j.get("model")
            headers = {"Content-Type": "application/json"}
            # key del request o, si falta, la guardada en el keyring para ese proveedor
            key = j.get("api_key") or (secrets.get_key(j_engine) if j_engine else None)
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

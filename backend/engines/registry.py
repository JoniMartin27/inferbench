"""Registro central de motores disponibles."""

from __future__ import annotations

from core.optimizer import ENGINE_QUANTS

from .base import Engine, EngineMeta, StartRequest
from .llamacpp import LlamaCppEngine
from .ollama import OllamaEngine
from .sglang import SglangEngine
from .stablediffusion import StableDiffusionEngine
from .tgi import TgiEngine
from .vllm import VllmEngine


class _ApiOnlyEngine(Engine):
    """Stub para motores cloud — no se arrancan por Docker."""

    def build_command(self, req: StartRequest) -> list[str]:
        raise NotImplementedError("Motor API no usa Docker")


def _api_meta(eid: str, name: str, desc: str) -> EngineMeta:
    return EngineMeta(
        id=eid,
        name=name,
        type="api",
        optimizable=False,
        description=desc,
        runtimes=[],
        default_runtime="docker",
    )


_REGISTRY: dict[str, Engine] = {}


def _register(engine: Engine) -> None:
    _REGISTRY[engine.meta.id] = engine


# Motores locales
_register(LlamaCppEngine())
_register(OllamaEngine())
_register(VllmEngine())
_register(SglangEngine())
_register(TgiEngine())
# Generación de imagen (stable-diffusion.cpp): solo runtime nativo, sin quants de UI.
_register(StableDiffusionEngine())


# Cuantizaciones válidas por motor (fuente única: optimizer.ENGINE_QUANTS). Las publicamos
# en la metadata para que la UI ofrezca los quants correctos por motor (GGUF en llama.cpp,
# awq/gptq/fp8 en los Docker). Ollama va por tag pre-cuantizado y las APIs no cuantizan → [].
def _attach_quants() -> None:
    _NO_QUANT_UI = {"ollama"}  # el quant lo fija el tag de Ollama
    for engine in _REGISTRY.values():
        if engine.meta.type == "api" or engine.meta.id in _NO_QUANT_UI:
            continue
        quants = list(ENGINE_QUANTS.get(engine.meta.id, []))
        if engine.meta.id in ("vllm", "sglang", "tgi"):
            quants = ["none", *quants]  # fp16 sin cuantizar = opción por defecto segura
        engine.meta.quants = quants


_attach_quants()


# APIs cloud
for eid, name, desc in [
    ("openai", "OpenAI", "API cloud — solo sampling."),
    ("anthropic", "Anthropic", "API cloud — solo sampling."),
    ("openrouter", "OpenRouter", "Agregador de APIs — solo sampling."),
    ("nvidia", "NVIDIA NIM", "API cloud — solo sampling."),
]:
    _register(_ApiOnlyEngine(_api_meta(eid, name, desc)))


def get_engine(engine_id: str) -> Engine:
    if engine_id not in _REGISTRY:
        raise KeyError(engine_id)
    return _REGISTRY[engine_id]


def list_engines() -> list[Engine]:
    return list(_REGISTRY.values())

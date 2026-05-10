"""Registro central de motores disponibles."""
from __future__ import annotations

from .base import Engine, EngineMeta
from .llamacpp import LlamaCppEngine
from .ollama import OllamaEngine
from .sglang import SglangEngine
from .tgi import TgiEngine
from .vllm import VllmEngine


class _ApiOnlyEngine(Engine):
    """Stub para motores cloud — no se arrancan por Docker."""

    def build_command(self, req):  # type: ignore[override]
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

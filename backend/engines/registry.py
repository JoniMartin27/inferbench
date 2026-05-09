"""Registro central de motores disponibles."""
from __future__ import annotations

from .base import Engine, EngineMeta
from .llamacpp import LlamaCppEngine


class _ApiOnlyEngine(Engine):
    """Stub para motores cloud — no se arrancan por Docker."""

    def build_command(self, req):  # type: ignore[override]
        raise NotImplementedError("Motor API no usa Docker")


def _api_meta(eid: str, name: str, desc: str) -> EngineMeta:
    return EngineMeta(
        id=eid, name=name, type="api", optimizable=False, description=desc,
        runtimes=[], default_runtime="docker",
    )


_REGISTRY: dict[str, Engine] = {}


def _register(engine: Engine) -> None:
    _REGISTRY[engine.meta.id] = engine


# Local (M2 implementa solo llamacpp; el resto se añadirán en sus propios hitos)
_register(LlamaCppEngine())

# Stubs locales pendientes (visibles en la lista pero solo Docker)
class _PendingLocal(Engine):
    def build_command(self, req):  # type: ignore[override]
        raise NotImplementedError(f"Motor {self.meta.id} aún no implementado")


for stub_id, stub_name, stub_image, stub_port in [
    ("ollama", "Ollama", "ollama/ollama:latest", 11434),
    ("vllm", "vLLM", "vllm/vllm-openai:latest", 8000),
    ("sglang", "SGLang", "lmsysorg/sglang:latest", 30000),
    ("tgi", "HF TGI", "ghcr.io/huggingface/text-generation-inference:latest", 8088),
]:
    _register(
        _PendingLocal(
            EngineMeta(
                id=stub_id,
                name=stub_name,
                type="local",
                default_port=stub_port,
                image=stub_image,
                optimizable=True,
                description="Pendiente de implementación. Requiere Docker.",
                runtimes=["docker"],
                default_runtime="docker",
            )
        )
    )

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

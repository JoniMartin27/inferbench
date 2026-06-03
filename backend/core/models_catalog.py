"""Carga del catálogo de modelos desde data/models.json."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "models.json"


class HfGguf(BaseModel):
    repo: str
    file_template: str  # debe contener {quant}, ej. "Llama-3.2-3B-Instruct-{quant}.gguf"
    mmproj: str | None = None  # filename del projector multimodal en el mismo repo (visión)


class Model(BaseModel):
    id: str
    name: str
    family: str
    params_b: float           # parámetros totales en miles de millones
    active_b: float           # activos por token (igual a params_b si no es MoE)
    is_moe: bool
    size_base_gb: float       # tamaño sin cuantizar (~ FP16) en GB
    max_ctx: int
    license: str = ""
    tags: list[str] = []
    hf_gguf: HfGguf | None = None  # fuente para auto-descarga (llama.cpp)
    ollama_tag: str | None = None  # tag en el registro de Ollama (ej. "llama3.2:1b")
    hf_repo: str | None = None     # repo HF del modelo no-cuantizado (vLLM/SGLang/TGI)
    n_layer: int | None = None     # número de capas (para ngl partial y KV exacta)
    n_head: int | None = None      # cabezas de atención (query)
    n_head_kv: int | None = None   # cabezas de KV (GQA/MQA); fija el tamaño de KV-cache
    head_dim: int | None = None    # dimensión por cabeza (para KV-cache exacta)

    @property
    def is_vision(self) -> bool:
        """Modelo multimodal de visión (necesita un mmproj para procesar imágenes)."""
        return "vision" in self.tags


@lru_cache(maxsize=1)
def load_models() -> list[Model]:
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return [Model.model_validate(m) for m in raw]


def get_model(model_id: str) -> Model | None:
    for m in load_models():
        if m.id == model_id:
            return m
    return None

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
    hf_gguf: HfGguf | None = None  # fuente para auto-descarga


@lru_cache(maxsize=1)
def load_models() -> list[Model]:
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return [Model.model_validate(m) for m in raw]


def get_model(model_id: str) -> Model | None:
    for m in load_models():
        if m.id == model_id:
            return m
    return None

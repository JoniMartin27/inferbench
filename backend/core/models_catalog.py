"""Carga del catálogo de modelos desde data/models.json."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "models.json"

Modality = Literal["text", "image", "video"]


class HfGguf(BaseModel):
    repo: str
    file_template: str  # debe contener {quant}, ej. "Llama-3.2-3B-Instruct-{quant}.gguf"
    mmproj: str | None = None  # filename del projector multimodal en el mismo repo (visión)
    multipart: bool = False  # GGUF partido en shards (-00001-of-000NN.gguf) para modelos enormes
    # --- Archivos de modelo single-file (no {quant}) ---
    # Modelos de imagen SD1.x/SDXL/SD-Turbo son un checkpoint único safetensors. Cuando
    # `file` está presente, model_manager lo usa tal cual (ignora file_template/{quant}).
    file: str | None = None  # filename exacto del checkpoint (ej. "sd_turbo.safetensors")
    # --- Archivos auxiliares (FLUX y difusión multi-archivo) ---
    # Diffusion-model standalone + encoders/VAE, todos en el MISMO repo HF (patrón mmproj).
    # Si `diffusion_model` está presente, el server sd.cpp carga con --diffusion-model en
    # vez de -m, y los auxiliares con sus flags (--vae/--clip_l/--clip_g/--t5xxl).
    diffusion_model: str | None = None  # filename del diffusion-model GGUF/safetensors
    vae: str | None = None  # filename del VAE
    clip_l: str | None = None  # filename del encoder CLIP-L
    clip_g: str | None = None  # filename del encoder CLIP-G (SDXL)
    t5xxl: str | None = None  # filename del encoder T5-XXL (FLUX)

    @property
    def aux_files(self) -> dict[str, str]:
        """Auxiliares declarados (kind→filename), para descargar y pasar al server sd.cpp."""
        out: dict[str, str] = {}
        for kind in ("diffusion_model", "vae", "clip_l", "clip_g", "t5xxl"):
            val = getattr(self, kind)
            if val:
                out[kind] = val
        return out


class ImageSpec(BaseModel):
    """Parámetros por defecto de generación de imagen (modelos modality='image')."""

    default_steps: int = 20
    default_size: tuple[int, int] = (512, 512)  # [width, height]
    default_cfg_scale: float = 7.0
    # Opciones de arranque del server sd.cpp (alivian VRAM en FLUX): se mapean a engine_opts.
    offload_to_cpu: bool = False
    diffusion_fa: bool = False


class Model(BaseModel):
    id: str
    name: str
    family: str
    params_b: float  # parámetros totales en miles de millones
    active_b: float  # activos por token (igual a params_b si no es MoE)
    is_moe: bool
    size_base_gb: float  # tamaño sin cuantizar (~ FP16) en GB
    max_ctx: int
    license: str = ""
    tags: list[str] = []
    # Modalidad de salida del modelo. "text" = LLM (default; el resto de campos asumen
    # texto). "image" = generación de imagen vía stable-diffusion.cpp. "video" = reservado
    # para una fase futura (sd.cpp soporta Wan2.1/LTX; aún no implementado).
    modality: Modality = "text"
    hf_gguf: HfGguf | None = None  # fuente para auto-descarga (llama.cpp / sd.cpp)
    ollama_tag: str | None = None  # tag en el registro de Ollama (ej. "llama3.2:1b")
    hf_repo: str | None = None  # repo HF del modelo no-cuantizado (vLLM/SGLang/TGI)
    n_layer: int | None = None  # número de capas (para ngl partial y KV exacta)
    n_head: int | None = None  # cabezas de atención (query)
    n_head_kv: int | None = None  # cabezas de KV (GQA/MQA); fija el tamaño de KV-cache
    head_dim: int | None = None  # dimensión por cabeza (para KV-cache exacta)
    image: ImageSpec | None = None  # defaults de generación (solo modality="image")

    @property
    def is_vision(self) -> bool:
        """Modelo multimodal de visión (necesita un mmproj para procesar imágenes)."""
        return "vision" in self.tags

    @property
    def is_image(self) -> bool:
        """Modelo de generación de imagen (se sirve con stable-diffusion.cpp)."""
        return self.modality == "image"


@lru_cache(maxsize=1)
def load_models() -> list[Model]:
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return [Model.model_validate(m) for m in raw]


def get_model(model_id: str) -> Model | None:
    for m in load_models():
        if m.id == model_id:
            return m
    return None

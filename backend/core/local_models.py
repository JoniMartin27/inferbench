"""Descubrimiento de modelos GGUF locales: escanea carpetas habituales y lee metadata."""
from __future__ import annotations

import os
import re
from pathlib import Path

from loguru import logger
from pydantic import BaseModel

from . import gguf_reader

# Carpetas conocidas donde herramientas populares guardan GGUFs
KNOWN_DIRS: list[Path] = []


def _add_if_exists(p: Path) -> None:
    if p and p.exists() and p.is_dir():
        KNOWN_DIRS.append(p)


# Inicialización: poblar dirs conocidos según OS
def _init_dirs() -> None:
    KNOWN_DIRS.clear()
    home = Path.home()
    appdata = Path(os.environ["APPDATA"]) if os.name == "nt" and "APPDATA" in os.environ else None
    localappdata = (
        Path(os.environ["LOCALAPPDATA"]) if os.name == "nt" and "LOCALAPPDATA" in os.environ else None
    )

    # InferBench propio
    if appdata:
        _add_if_exists(appdata / "InferBench" / "models")
    _add_if_exists(home / ".inferbench" / "models")

    # LM Studio (Windows + Mac/Linux)
    _add_if_exists(home / ".cache" / "lm-studio" / "models")
    _add_if_exists(home / ".lmstudio" / "models")
    if localappdata:
        _add_if_exists(localappdata / "LM-Studio" / "models")

    # Jan.ai
    _add_if_exists(home / "jan" / "models")
    _add_if_exists(home / ".jan" / "models")

    # Hugging Face cache
    _add_if_exists(home / ".cache" / "huggingface" / "hub")

    # llama.cpp default
    _add_if_exists(home / ".cache" / "llama.cpp")
    _add_if_exists(home / "llama.cpp" / "models")

    # GPT4All
    if localappdata:
        _add_if_exists(localappdata / "nomic.ai" / "GPT4All")
    _add_if_exists(home / ".cache" / "gpt4all")

    # Carpetas comunes en escritorio (best-effort)
    for dir_name in ("Desktop", "Documents", "Downloads"):
        _add_if_exists(home / dir_name / "models")
        _add_if_exists(home / dir_name / "gguf")
        _add_if_exists(home / dir_name / "LLM")


_init_dirs()


# Heurística para detectar quantización por nombre de fichero
_QUANT_PATTERNS = [
    "Q2_K", "Q3_K_S", "Q3_K_M", "Q3_K_L",
    "Q4_0", "Q4_1", "Q4_K_S", "Q4_K_M",
    "Q5_0", "Q5_1", "Q5_K_S", "Q5_K_M",
    "Q6_K", "Q8_0",
    "IQ1_S", "IQ1_M", "IQ2_XXS", "IQ2_XS", "IQ2_S", "IQ2_M",
    "IQ3_XXS", "IQ3_S", "IQ3_M", "IQ3_XS",
    "IQ4_XS", "IQ4_NL",
    "F16", "FP16", "BF16", "F32",
]


def _detect_quant(filename: str) -> str | None:
    upper = filename.upper()
    for q in _QUANT_PATTERNS:
        if f"-{q}." in upper or f"_{q}." in upper or f".{q}." in upper:
            return q
    return None


_QUANT_FACTOR = {
    "Q2_K": 0.32, "Q3_K_S": 0.40, "Q3_K_M": 0.42, "Q3_K_L": 0.46,
    "Q4_0": 0.52, "Q4_1": 0.55, "Q4_K_S": 0.53, "Q4_K_M": 0.55,
    "Q5_0": 0.65, "Q5_1": 0.68, "Q5_K_S": 0.65, "Q5_K_M": 0.67,
    "Q6_K": 0.81, "Q8_0": 1.0, "F16": 2.0, "FP16": 2.0, "BF16": 2.0, "F32": 4.0,
    "IQ4_XS": 0.50, "IQ4_NL": 0.52, "IQ3_M": 0.40, "IQ3_S": 0.38, "IQ2_M": 0.30,
}


class LocalModel(BaseModel):
    path: str
    filename: str
    dir: str
    size_gb: float
    quant: str | None = None
    architecture: str | None = None
    name: str | None = None
    params_b: float | None = None
    n_layer: int | None = None
    n_head: int | None = None
    n_head_kv: int | None = None
    head_dim: int | None = None
    context_length: int | None = None
    is_moe: bool = False
    error: str | None = None


def _estimate_params(size_bytes: int, quant: str | None) -> float | None:
    if not quant:
        return None
    factor = _QUANT_FACTOR.get(quant.upper())
    if not factor:
        return None
    # bytes_per_param_FP16 = 2 → params_b ≈ (size_GB / factor) / 2
    size_gb = size_bytes / (1024**3)
    return round((size_gb / factor) / 2, 2)


def _enrich_with_metadata(m: LocalModel) -> LocalModel:
    try:
        meta = gguf_reader.read_gguf_metadata(Path(m.path))
        s = gguf_reader.summarize(meta)
        m.architecture = s.get("architecture")
        m.name = s.get("name")
        m.n_layer = s.get("n_layer")
        m.n_head = s.get("n_head")
        m.n_head_kv = s.get("n_head_kv")
        m.head_dim = s.get("head_dim")
        m.context_length = s.get("context_length")
        # MoE detection: keys con "expert"
        m.is_moe = any("expert" in k.lower() for k in meta.keys())
        # Cuenta de parámetros real desde la metadata (independiente del quant)
        pc = gguf_reader.estimate_param_count(meta)
        if pc:
            m.params_b = round(pc / 1e9, 2)
    except Exception as e:
        m.error = f"GGUF metadata: {e}"
    return m


def get_extra_dirs_file() -> Path:
    base = (
        Path(os.environ["APPDATA"]) / "InferBench"
        if os.name == "nt" and "APPDATA" in os.environ
        else Path.home() / ".inferbench"
    )
    base.mkdir(parents=True, exist_ok=True)
    return base / "extra_model_dirs.txt"


def get_extra_dirs() -> list[Path]:
    f = get_extra_dirs_file()
    if not f.exists():
        return []
    out: list[Path] = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = Path(line)
        if p.exists() and p.is_dir():
            out.append(p)
    return out


def set_extra_dirs(dirs: list[str]) -> list[Path]:
    f = get_extra_dirs_file()
    f.write_text("\n".join(dirs), encoding="utf-8")
    return get_extra_dirs()


def all_search_dirs() -> list[Path]:
    return list({d.resolve(): d for d in KNOWN_DIRS + get_extra_dirs()}.values())


def discover(read_metadata: bool = True, max_per_dir: int = 200) -> list[LocalModel]:
    """Escanea las carpetas conocidas + extra y devuelve los GGUFs encontrados."""
    seen: set[str] = set()
    found: list[LocalModel] = []
    for d in all_search_dirs():
        try:
            count = 0
            for gguf in d.rglob("*.gguf"):
                key = str(gguf.resolve())
                if key in seen:
                    continue
                seen.add(key)
                count += 1
                if count > max_per_dir:
                    break
                try:
                    stat = gguf.stat()
                except OSError:
                    continue
                quant = _detect_quant(gguf.name)
                m = LocalModel(
                    path=str(gguf),
                    filename=gguf.name,
                    dir=str(gguf.parent),
                    size_gb=round(stat.st_size / (1024**3), 2),
                    quant=quant,
                )
                if read_metadata:
                    m = _enrich_with_metadata(m)
                if m.params_b is None:
                    m.params_b = _estimate_params(stat.st_size, quant)
                found.append(m)
        except Exception as e:
            logger.warning(f"Error escaneando {d}: {e}")
    return sorted(found, key=lambda m: m.size_gb)

"""Descubrimiento de modelos GGUF locales: escanea carpetas habituales y lee metadata."""

from __future__ import annotations

import json
import os
import threading
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
        Path(os.environ["LOCALAPPDATA"])
        if os.name == "nt" and "LOCALAPPDATA" in os.environ
        else None
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
    "Q2_K",
    "Q3_K_S",
    "Q3_K_M",
    "Q3_K_L",
    "Q4_0",
    "Q4_1",
    "Q4_K_S",
    "Q4_K_M",
    "Q5_0",
    "Q5_1",
    "Q5_K_S",
    "Q5_K_M",
    "Q6_K",
    "Q8_0",
    "IQ1_S",
    "IQ1_M",
    "IQ2_XXS",
    "IQ2_XS",
    "IQ2_S",
    "IQ2_M",
    "IQ3_XXS",
    "IQ3_S",
    "IQ3_M",
    "IQ3_XS",
    "IQ4_XS",
    "IQ4_NL",
    "F16",
    "FP16",
    "BF16",
    "F32",
]


def _detect_quant(filename: str) -> str | None:
    upper = filename.upper()
    for q in _QUANT_PATTERNS:
        if f"-{q}." in upper or f"_{q}." in upper or f".{q}." in upper:
            return q
    return None


_QUANT_FACTOR = {
    "Q2_K": 0.32,
    "Q3_K_S": 0.40,
    "Q3_K_M": 0.42,
    "Q3_K_L": 0.46,
    "Q4_0": 0.52,
    "Q4_1": 0.55,
    "Q4_K_S": 0.53,
    "Q4_K_M": 0.55,
    "Q5_0": 0.65,
    "Q5_1": 0.68,
    "Q5_K_S": 0.65,
    "Q5_K_M": 0.67,
    "Q6_K": 0.81,
    "Q8_0": 1.0,
    "F16": 2.0,
    "FP16": 2.0,
    "BF16": 2.0,
    "F32": 4.0,
    "IQ4_XS": 0.50,
    "IQ4_NL": 0.52,
    "IQ3_M": 0.40,
    "IQ3_S": 0.38,
    "IQ2_M": 0.30,
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


def _state_dir() -> Path:
    base = (
        Path(os.environ["APPDATA"]) / "InferBench"
        if os.name == "nt" and "APPDATA" in os.environ
        else Path.home() / ".inferbench"
    )
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_extra_dirs_file() -> Path:
    return _state_dir() / "extra_model_dirs.txt"


# --- Caché de metadata GGUF -------------------------------------------------------------
#
# MEDIDO sobre 28 GGUFs locales: el rglob de las ~20 carpetas cuesta 5 ms y construir los
# LocalModel sin metadata 16 ms, pero leer las cabeceras GGUF cuesta **5,7 s** (~204 ms por
# fichero). O sea el 99,7% del coste es la metadata. Y como `ModelsView`/`GuideView` piden
# el listado en cada montaje, se re-leía todo entero cada vez que cambiabas de pestaña, con
# el event loop ahogado durante segundos (`/api/engines` pasaba de 63 ms a ~1,8 s).
#
# Por eso la caché es POR FICHERO y no del resultado entero: el rglob se sigue haciendo
# siempre (cuesta 5 ms), así que un GGUF nuevo o borrado aparece/desaparece al instante;
# solo se paga la lectura de cabecera de los ficheros que no estaban cacheados. La clave
# lleva mtime y tamaño, de modo que un fichero reemplazado se vuelve a leer solo.
#
# Se persiste a disco para que el arranque en frío (abrir la app) tampoco pague los 5,7 s.
_CACHE_VERSION = 1
_meta_cache: dict[str, dict] | None = None
_meta_cache_lock = threading.Lock()
_meta_cache_dirty = False


def _meta_cache_file() -> Path:
    return _state_dir() / "gguf_meta_cache.json"


def _cache_key(path: Path, size: int, mtime_ns: int) -> str:
    return f"{path.resolve()}|{size}|{mtime_ns}"


def _load_meta_cache() -> dict[str, dict]:
    global _meta_cache
    if _meta_cache is not None:
        return _meta_cache
    _meta_cache = {}
    f = _meta_cache_file()
    try:
        if f.exists():
            raw = json.loads(f.read_text(encoding="utf-8"))
            if raw.get("version") == _CACHE_VERSION and isinstance(raw.get("entries"), dict):
                _meta_cache = raw["entries"]
    except Exception as e:  # caché corrupta: se regenera, nunca rompe el escaneo
        logger.warning(f"Caché de metadata GGUF ilegible ({e}); la regenero")
        _meta_cache = {}
    return _meta_cache


def _save_meta_cache() -> None:
    global _meta_cache_dirty
    if not _meta_cache_dirty or _meta_cache is None:
        return
    try:
        tmp = _meta_cache_file().with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps({"version": _CACHE_VERSION, "entries": _meta_cache}),
            encoding="utf-8",
        )
        tmp.replace(_meta_cache_file())
        _meta_cache_dirty = False
    except Exception as e:  # no poder cachear no es motivo para fallar
        logger.warning(f"No pude guardar la caché de metadata GGUF: {e}")


def clear_meta_cache() -> None:
    """Olvida la metadata cacheada (en memoria y en disco). La usa `discover(refresh=True)`."""
    global _meta_cache, _meta_cache_dirty
    with _meta_cache_lock:
        _meta_cache = {}
        _meta_cache_dirty = False
        try:
            _meta_cache_file().unlink(missing_ok=True)
        except OSError as e:
            logger.warning(f"No pude borrar la caché de metadata GGUF: {e}")


# Campos de LocalModel que rellena la lectura de cabecera y que, por tanto, cacheamos.
_CACHED_FIELDS = (
    "architecture",
    "name",
    "params_b",
    "n_layer",
    "n_head",
    "n_head_kv",
    "head_dim",
    "context_length",
    "is_moe",
    "error",
)


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


def discover(
    read_metadata: bool = True, max_per_dir: int = 200, refresh: bool = False
) -> list[LocalModel]:
    """Escanea las carpetas conocidas + extra y devuelve los GGUFs encontrados.

    `refresh=True` tira la caché de metadata y vuelve a leer todas las cabeceras GGUF.
    """
    if refresh:
        clear_meta_cache()

    seen: set[str] = set()
    found: list[LocalModel] = []
    cache = _load_meta_cache() if read_metadata else {}
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
                    m = _enrich_cached(m, cache, stat.st_size, stat.st_mtime_ns)
                if m.params_b is None:
                    m.params_b = _estimate_params(stat.st_size, quant)
                found.append(m)
        except Exception as e:
            logger.warning(f"Error escaneando {d}: {e}")

    if read_metadata:
        with _meta_cache_lock:
            _save_meta_cache()
    return sorted(found, key=lambda m: m.size_gb)


def _enrich_cached(m: LocalModel, cache: dict[str, dict], size: int, mtime_ns: int) -> LocalModel:
    """`_enrich_with_metadata` pasando primero por la caché por fichero."""
    global _meta_cache_dirty
    key = _cache_key(Path(m.path), size, mtime_ns)
    hit = cache.get(key)
    if hit is not None:
        for field in _CACHED_FIELDS:
            if field in hit:
                setattr(m, field, hit[field])
        return m

    m = _enrich_with_metadata(m)
    cache[key] = {field: getattr(m, field) for field in _CACHED_FIELDS}
    _meta_cache_dirty = True
    return m

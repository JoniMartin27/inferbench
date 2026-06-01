"""Lector mínimo de metadata GGUF.

Spec: https://github.com/ggml-org/ggml/blob/master/docs/gguf.md
Sólo extrae los KV de la cabecera; ignora tensores. Suficiente para detectar
arquitectura, nombre, n_layer, n_kv_heads, head_dim, contexto, etc.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Any

GGUF_MAGIC = 0x46554747  # "GGUF" little-endian


class GGUFType:
    UINT8 = 0
    INT8 = 1
    UINT16 = 2
    INT16 = 3
    UINT32 = 4
    INT32 = 5
    FLOAT32 = 6
    BOOL = 7
    STRING = 8
    ARRAY = 9
    UINT64 = 10
    INT64 = 11
    FLOAT64 = 12


def _read_string(data: bytes, offset: int) -> tuple[str, int]:
    (length,) = struct.unpack_from("<Q", data, offset)
    offset += 8
    s = data[offset : offset + length].decode("utf-8", errors="replace")
    return s, offset + length


def _read_value(data: bytes, offset: int, value_type: int) -> tuple[Any, int]:
    if value_type == GGUFType.UINT32:
        v, = struct.unpack_from("<I", data, offset); return v, offset + 4
    if value_type == GGUFType.INT32:
        v, = struct.unpack_from("<i", data, offset); return v, offset + 4
    if value_type == GGUFType.FLOAT32:
        v, = struct.unpack_from("<f", data, offset); return v, offset + 4
    if value_type == GGUFType.BOOL:
        v, = struct.unpack_from("<?", data, offset); return v, offset + 1
    if value_type == GGUFType.STRING:
        return _read_string(data, offset)
    if value_type == GGUFType.UINT64:
        v, = struct.unpack_from("<Q", data, offset); return v, offset + 8
    if value_type == GGUFType.INT64:
        v, = struct.unpack_from("<q", data, offset); return v, offset + 8
    if value_type == GGUFType.FLOAT64:
        v, = struct.unpack_from("<d", data, offset); return v, offset + 8
    if value_type == GGUFType.UINT8:
        v, = struct.unpack_from("<B", data, offset); return v, offset + 1
    if value_type == GGUFType.INT8:
        v, = struct.unpack_from("<b", data, offset); return v, offset + 1
    if value_type == GGUFType.UINT16:
        v, = struct.unpack_from("<H", data, offset); return v, offset + 2
    if value_type == GGUFType.INT16:
        v, = struct.unpack_from("<h", data, offset); return v, offset + 2
    if value_type == GGUFType.ARRAY:
        arr_type, = struct.unpack_from("<I", data, offset); offset += 4
        arr_len, = struct.unpack_from("<Q", data, offset); offset += 8
        # Saltamos el contenido del array — sólo nos interesa el conteo
        for _ in range(arr_len):
            _, offset = _read_value(data, offset, arr_type)
        return f"<array[{arr_len}]>", offset
    raise ValueError(f"Tipo GGUF desconocido: {value_type}")


def read_gguf_metadata(path: Path, max_header_bytes: int = 16 * 1024 * 1024) -> dict[str, Any]:
    """Lee la metadata KV de un fichero GGUF y devuelve un dict {key: value}.

    Lee `max_header_bytes` desde el principio (16MB cubre incluso vocabularios
    grandes). Lanza ValueError si no es GGUF o el header está corrupto.
    """
    with open(path, "rb") as f:
        data = f.read(max_header_bytes)

    if len(data) < 24:
        raise ValueError("Archivo demasiado corto para ser GGUF")

    offset = 0
    magic, = struct.unpack_from("<I", data, offset); offset += 4
    if magic != GGUF_MAGIC:
        raise ValueError(f"No es GGUF (magic=0x{magic:08x})")

    version, = struct.unpack_from("<I", data, offset); offset += 4
    tensor_count, = struct.unpack_from("<Q", data, offset); offset += 8
    kv_count, = struct.unpack_from("<Q", data, offset); offset += 8

    kv: dict[str, Any] = {"_gguf_version": version, "_tensor_count": tensor_count}
    for _ in range(kv_count):
        try:
            key, offset = _read_string(data, offset)
            value_type, = struct.unpack_from("<I", data, offset); offset += 4
            value, offset = _read_value(data, offset, value_type)
        except (struct.error, IndexError, ValueError):
            break  # header truncado o tipo desconocido — devolver lo que ya tenemos
        kv[key] = value
    return kv


# Arquitecturas que comparten (tie) el embedding de entrada con la capa de salida.
# En ellas el lm_head no añade params; en el resto se cuenta aparte.
_TIE_ARCHS = {"gemma", "gemma2", "gemma3"}


def _array_len(v: Any) -> int | None:
    """El lector guarda los arrays como '<array[N]>'; extrae N (p.ej. tamaño de vocab)."""
    if isinstance(v, str):
        m = re.match(r"<array\[(\d+)\]>", v)
        if m:
            return int(m.group(1))
    return None


def _parse_size_label(sl: Any) -> float | None:
    """'1B'→1e9, '1.5B'→1.5e9, '360M'→360e6. Devuelve None para formatos MoE ('8x7B')."""
    if not isinstance(sl, str):
        return None
    m = re.match(r"^\s*([\d.]+)\s*([BM])\s*$", sl, re.IGNORECASE)
    if not m:
        return None
    return float(m.group(1)) * (1e9 if m.group(2).upper() == "B" else 1e6)


def estimate_param_count(meta: dict[str, Any]) -> int | None:
    """Cuenta de parámetros REAL (independiente del quant) a partir de la metadata.

    Prioridad: general.parameter_count → cálculo desde dimensiones de arquitectura
    (con desambiguación tied/untied vía size_label) → general.size_label.
    Mucho más fiable que estimar desde el tamaño de archivo, que varía con el quant.
    """
    arch = meta.get("general.architecture", "")
    pc = meta.get("general.parameter_count")
    if pc:
        try:
            return int(pc)
        except (TypeError, ValueError):
            pass

    size_label_pc = _parse_size_label(meta.get("general.size_label"))

    n_layer = meta.get(f"{arch}.block_count")
    n_embd = meta.get(f"{arch}.embedding_length")
    n_ff = meta.get(f"{arch}.feed_forward_length")
    n_head = meta.get(f"{arch}.attention.head_count")
    n_head_kv = meta.get(f"{arch}.attention.head_count_kv") or n_head
    head_dim = meta.get(f"{arch}.attention.key_length") or (
        (n_embd // n_head) if (n_embd and n_head) else None
    )
    vocab = meta.get(f"{arch}.vocab_size") or _array_len(meta.get("tokenizer.ggml.tokens"))
    n_expert = meta.get(f"{arch}.expert_count") or 0
    n_ff_exp = meta.get(f"{arch}.expert_feed_forward_length") or n_ff

    if not (n_layer and n_embd and n_ff and n_head and head_dim):
        return int(size_label_pc) if size_label_pc else None

    q_dim = n_head * head_dim
    kv_dim = n_head_kv * head_dim
    attn = n_embd * q_dim + 2 * n_embd * kv_dim + q_dim * n_embd  # q, k, v, o
    if n_expert and n_expert > 1:
        ffn = n_expert * (3 * n_embd * n_ff_exp) + n_embd * n_expert  # expertos + router
    else:
        ffn = 3 * n_embd * n_ff  # SwiGLU: gate + up + down
    body = n_layer * (attn + ffn + 2 * n_embd)  # +norms (despreciable)
    emb = (vocab or 0) * n_embd
    tied = body + emb
    untied = body + 2 * emb

    if size_label_pc:
        return int(tied if abs(tied - size_label_pc) <= abs(untied - size_label_pc) else untied)
    if arch in _TIE_ARCHS:
        return int(tied)
    return int(untied)


def summarize(meta: dict[str, Any]) -> dict[str, Any]:
    """Resumen amigable de la metadata GGUF."""
    arch = meta.get("general.architecture", "?")
    name = meta.get("general.name") or meta.get("general.basename") or ""
    quant_v = meta.get("general.file_type") or meta.get("general.quantization_version")
    n_layer = meta.get(f"{arch}.block_count")
    n_head = meta.get(f"{arch}.attention.head_count")
    n_head_kv = meta.get(f"{arch}.attention.head_count_kv") or n_head
    n_embd = meta.get(f"{arch}.embedding_length")
    ctx = meta.get(f"{arch}.context_length")
    head_dim = (n_embd // n_head) if (n_embd and n_head) else None
    return {
        "architecture": arch,
        "name": name,
        "n_layer": n_layer,
        "n_head": n_head,
        "n_head_kv": n_head_kv,
        "n_embd": n_embd,
        "head_dim": head_dim,
        "context_length": ctx,
        "file_type": quant_v,
    }

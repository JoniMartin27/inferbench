"""Lector mínimo de metadata GGUF.

Spec: https://github.com/ggml-org/ggml/blob/master/docs/gguf.md
Sólo extrae los KV de la cabecera; ignora tensores. Suficiente para detectar
arquitectura, nombre, n_layer, n_kv_heads, head_dim, contexto, etc.
"""
from __future__ import annotations

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
        key, offset = _read_string(data, offset)
        value_type, = struct.unpack_from("<I", data, offset); offset += 4
        try:
            value, offset = _read_value(data, offset, value_type)
        except (struct.error, IndexError, ValueError):
            break  # header truncado o tipo desconocido — devolver lo que ya tenemos
        kv[key] = value
    return kv


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

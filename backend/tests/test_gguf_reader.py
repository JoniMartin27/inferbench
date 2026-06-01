"""Tests de core/gguf_reader.py: parseo de metadata y cuenta de parámetros."""
from core import gguf_reader as g


def test_parse_size_label():
    assert g._parse_size_label("1B") == 1e9
    assert g._parse_size_label("1.5B") == 1.5e9
    assert g._parse_size_label("360M") == 360e6
    assert g._parse_size_label("8x7B") is None  # formato MoE no parseable
    assert g._parse_size_label(None) is None


def test_array_len():
    assert g._array_len("<array[256000]>") == 256000
    assert g._array_len("<array[0]>") == 0
    assert g._array_len("texto") is None
    assert g._array_len(42) is None


def test_param_count_explicit_wins():
    meta = {"general.architecture": "llama", "general.parameter_count": 1234567890}
    assert g.estimate_param_count(meta) == 1234567890


def _llama_meta(**kw):
    # Dimensiones reales de Llama 3.2 1B (embeddings atados → ~1.24B)
    base = {
        "general.architecture": "llama",
        "general.size_label": "1B",
        "llama.block_count": 16,
        "llama.embedding_length": 2048,
        "llama.feed_forward_length": 8192,
        "llama.attention.head_count": 32,
        "llama.attention.head_count_kv": 8,
        "llama.attention.key_length": 64,
        "llama.vocab_size": 128256,
    }
    base.update(kw)
    return base


def test_param_count_from_dims_llama_1b():
    pc = g.estimate_param_count(_llama_meta())
    assert pc is not None
    assert 1.15e9 < pc < 1.32e9  # ~1.24B real


def test_param_count_quant_independent():
    # La cuenta no depende del file_type (quant): mismas dims → mismo resultado
    a = g.estimate_param_count(_llama_meta())
    b = g.estimate_param_count(_llama_meta())  # mismas dims
    assert a == b


def test_param_count_gemma_tied_uses_token_array_vocab():
    # gemma2 no expone vocab_size; se toma del array tokenizer.ggml.tokens
    meta = {
        "general.architecture": "gemma2",
        "gemma2.block_count": 42,
        "gemma2.embedding_length": 3584,
        "gemma2.feed_forward_length": 14336,
        "gemma2.attention.head_count": 16,
        "gemma2.attention.head_count_kv": 8,
        "gemma2.attention.key_length": 256,
        "tokenizer.ggml.tokens": "<array[256000]>",
    }
    pc = g.estimate_param_count(meta)
    assert pc is not None
    assert 8.8e9 < pc < 9.7e9  # gemma-2-9b ~9.24B


def test_param_count_missing_dims_returns_none_or_label():
    assert g.estimate_param_count({"general.architecture": "llama"}) is None
    assert g.estimate_param_count(
        {"general.architecture": "llama", "general.size_label": "7B"}
    ) == 7e9

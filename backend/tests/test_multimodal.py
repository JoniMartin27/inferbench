"""Tests del soporte multimodal (visión): catálogo, mmproj y payload de la API."""
import base64

from core import benchmark, model_manager
from core.benchmark import Prompt, _build_chat_body, _image_data_url
from core.models_catalog import get_model

VISION_IDS = ["qwen2-vl-7b", "qwen2-vl-2b", "qwen2.5-vl-7b", "minicpm-v-2.6"]


def test_vision_models_flagged_and_have_mmproj():
    for mid in VISION_IDS:
        m = get_model(mid)
        assert m is not None, mid
        assert m.is_vision, f"{mid} debería ser is_vision"
        assert m.hf_gguf and m.hf_gguf.mmproj, f"{mid} debería tener hf_gguf.mmproj"
        assert m.hf_gguf.mmproj.endswith(".gguf")


def test_non_vision_model_not_flagged():
    m = get_model("llama-3-8b")
    assert m is not None and not m.is_vision
    assert not (m.hf_gguf and m.hf_gguf.mmproj)


def test_mmproj_path_in_same_dir_as_gguf():
    m = get_model("qwen2-vl-2b")
    gguf = model_manager.gguf_path(m, "Q4_K_M")
    mm = model_manager.mmproj_path(m)
    assert mm is not None
    assert mm.parent == gguf.parent  # mismo repo dir → fácil de montar/servir
    assert mm.name == m.hf_gguf.mmproj


def test_mmproj_path_none_for_non_vision():
    assert model_manager.mmproj_path(get_model("llama-3-8b")) is None


def test_chat_body_text_only_is_string():
    p = Prompt(id="t", name="T", type="chat", prompt="hola", system="sys")
    body = _build_chat_body("m", p, {"temperature": 0.7})
    user = next(msg for msg in body["messages"] if msg["role"] == "user")
    assert user["content"] == "hola"  # texto plano, no array
    assert body["temperature"] == 0.7


def test_chat_body_with_image_is_multimodal_array():
    p = Prompt(id="vision", name="V", type="vision", prompt="¿qué ves?", image="vision_test.png")
    body = _build_chat_body("m", p, {})
    user = next(msg for msg in body["messages"] if msg["role"] == "user")
    assert isinstance(user["content"], list)
    assert [part["type"] for part in user["content"]] == ["text", "image_url"]
    assert user["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_vision_test_asset_exists_and_decodes():
    head, b64 = _image_data_url("vision_test.png").split(",", 1)
    assert head == "data:image/png;base64"
    assert base64.b64decode(b64)[:8] == b"\x89PNG\r\n\x1a\n"  # PNG válido


def test_vision_prompt_registered_in_suite():
    p = benchmark.get_prompt("vision")
    assert p is not None and p.type == "vision" and p.image == "vision_test.png"

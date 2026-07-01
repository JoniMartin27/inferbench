"""Tests del soporte multimodal (visión): catálogo, mmproj, payload y scorer de calidad."""

import base64

from core import benchmark, model_manager
from core.benchmark import Prompt, _build_chat_body, _image_data_url, _quality_keywords
from core.models_catalog import get_model

VISION_IDS = ["qwen2-vl-7b", "qwen2-vl-2b", "qwen2.5-vl-7b", "minicpm-v-2.6"]
VISION_PROMPTS = ["vision-scene", "vision-count"]


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


def test_supports_vision_gating():
    from core.benchmark import supports_vision

    vis, txt = get_model("qwen2-vl-2b"), get_model("llama-3-8b")
    # APIs cloud: siempre (gpt-4o, claude… multimodales)
    assert supports_vision("openai", txt) is True
    assert supports_vision("anthropic", None) is True
    # Local (llama.cpp) y Docker (vLLM): solo si el modelo es de visión
    assert supports_vision("llamacpp", vis) is True
    assert supports_vision("vllm", vis) is True  # Docker + modelo de visión → sí
    assert supports_vision("llamacpp", txt) is False
    assert supports_vision("vllm", txt) is False


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
    p = Prompt(id="v", name="V", type="vision", prompt="¿qué ves?", image="vision_scene.png")
    body = _build_chat_body("m", p, {})
    user = next(msg for msg in body["messages"] if msg["role"] == "user")
    assert isinstance(user["content"], list)
    assert [part["type"] for part in user["content"]] == ["text", "image_url"]
    assert user["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_vision_assets_exist_and_decode():
    for img in ("vision_scene.png", "vision_count.png"):
        head, b64 = _image_data_url(img).split(",", 1)
        assert head == "data:image/png;base64"
        assert base64.b64decode(b64)[:8] == b"\x89PNG\r\n\x1a\n"  # PNG válido


def test_vision_prompts_registered_with_checklist():
    for pid in VISION_PROMPTS:
        p = benchmark.get_prompt(pid)
        assert p is not None and p.type == "vision"
        assert p.image and p.image.endswith(".png")
        assert p.keywords and all(isinstance(g, list) and g for g in p.keywords)


# ---- scorer por checklist (la mejora de calidad de verdad) ----

GROUPS = [["círculo", "circle"], ["rojo", "red"], ["3", "tres", "three"]]


def test_keywords_perfect_match_is_100():
    assert _quality_keywords("Hay 3: un círculo rojo y más", GROUPS) == 100.0


def test_keywords_partial_is_fraction():
    # acierta círculo (1/3) pero no color ni conteo
    assert _quality_keywords("Veo un circulo", GROUPS) == round(1 / 3 * 100, 1)


def test_keywords_empty_output_is_zero():
    assert _quality_keywords("", GROUPS) == 0.0
    assert _quality_keywords("nada relevante", GROUPS) == 0.0


def test_keywords_accent_and_language_insensitive():
    # 'circulo' (sin tilde) y términos en inglés cuentan igual
    assert _quality_keywords("a red circle, three of them", GROUPS) == 100.0
    assert _quality_keywords("un circulo", [["círculo"]]) == 100.0


def test_scene_checklist_scores_a_correct_answer_high():
    # Respuesta ideal a vision-scene → debería puntuar 100 con su propio checklist.
    p = benchmark.get_prompt("vision-scene")
    ideal = "Hay 3 figuras: un círculo rojo, un cuadrado azul y un triángulo verde."
    assert _quality_keywords(ideal, p.keywords) == 100.0
    # Una respuesta pobre puntúa mucho menos.
    assert _quality_keywords("Una figura azul.", p.keywords) < 50.0

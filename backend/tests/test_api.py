"""Tests de la construcción de peticiones a APIs cloud.

Anthropic NO es OpenAI-compatible: endpoint /v1/messages, `system` aparte, `max_tokens`
obligatorio, imágenes como bloque base64. El resto (OpenAI/OpenRouter/NVIDIA) usan
/v1/chat/completions. Estos tests fijan ambas formas sin tocar la red.
"""
from core.benchmark import Prompt, _build_anthropic_body, _build_chat_body


def test_anthropic_body_system_is_top_level():
    p = Prompt(id="t", name="T", type="chat", prompt="hola", system="eres conciso")
    body = _build_anthropic_body("claude-x", p, {"temperature": 0.5})
    assert body["system"] == "eres conciso"  # system aparte, NO como mensaje de rol
    assert body["max_tokens"] == p.target_tokens  # obligatorio en Anthropic
    assert body["messages"] == [{"role": "user", "content": "hola"}]
    assert all(m["role"] != "system" for m in body["messages"])
    assert body["temperature"] == 0.5


def test_anthropic_body_image_is_base64_block():
    p = Prompt(id="v", name="V", type="vision", prompt="¿qué ves?", image="vision_scene.png")
    body = _build_anthropic_body("claude-x", p, {})
    content = body["messages"][0]["content"]
    assert isinstance(content, list)
    img = next(c for c in content if c["type"] == "image")
    assert img["source"]["type"] == "base64"
    assert img["source"]["media_type"] == "image/png"
    assert img["source"]["data"]  # base64 no vacío


def test_openai_body_uses_system_message_role():
    p = Prompt(id="t", name="T", type="chat", prompt="hola", system="sys")
    body = _build_chat_body("gpt-x", p, {})
    assert [m["role"] for m in body["messages"]] == ["system", "user"]  # OpenAI: system como rol
    assert "max_tokens" in body

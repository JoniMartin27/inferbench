"""Tests de core/secrets.py y /api/keys con keyring mockeado (no toca el del SO)."""
import pytest

from core import secrets


@pytest.fixture
def fake_keyring(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(secrets.keyring, "set_password", lambda s, p, k: store.__setitem__((s, p), k))
    monkeypatch.setattr(secrets.keyring, "get_password", lambda s, p: store.get((s, p)))
    monkeypatch.setattr(secrets.keyring, "delete_password", lambda s, p: store.pop((s, p), None))
    return store


def test_secrets_set_get_delete(fake_keyring):
    assert secrets.get_key("openai") is None
    secrets.set_key("openai", "sk-test")
    assert secrets.get_key("openai") == "sk-test"
    secrets.delete_key("openai")
    assert secrets.get_key("openai") is None


def test_has_keys_only_presence(fake_keyring):
    secrets.set_key("anthropic", "sk-ant-x")
    h = secrets.has_keys()
    assert h["anthropic"] is True and h["openai"] is False
    assert set(h) == set(secrets.PROVIDERS)


def test_keys_endpoint_roundtrip(fake_keyring):
    from fastapi.testclient import TestClient

    from main import app

    c = TestClient(app)
    assert c.get("/api/keys").json()["openai"] is False
    assert c.post("/api/keys", json={"provider": "openai", "key": "sk-x"}).status_code == 200
    assert c.get("/api/keys").json()["openai"] is True
    assert c.delete("/api/keys/openai").status_code == 200
    assert c.get("/api/keys").json()["openai"] is False


def test_keys_endpoint_validation(fake_keyring):
    from fastapi.testclient import TestClient

    from main import app

    c = TestClient(app)
    assert c.post("/api/keys", json={"provider": "nope", "key": "x"}).status_code == 400
    assert c.post("/api/keys", json={"provider": "openai", "key": "  "}).status_code == 400

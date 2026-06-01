"""Tests de endurecimiento: host confiable de descargas + defensa DNS-rebinding."""
from core.binary_manager import _is_trusted_dl_host


def test_trusted_download_hosts():
    assert _is_trusted_dl_host("https://github.com/o/r/releases/download/v/a.zip")
    assert _is_trusted_dl_host("https://objects.githubusercontent.com/x/a.zip")
    assert _is_trusted_dl_host("https://release-assets.githubusercontent.com/a.zip")


def test_untrusted_download_hosts_rejected():
    assert not _is_trusted_dl_host("https://evil.com/a.zip")
    assert not _is_trusted_dl_host("https://github.com.evil.com/a.zip")  # spoof subdominio
    assert not _is_trusted_dl_host("https://notgithub.com/a.zip")


def test_dns_rebinding_middleware():
    from fastapi.testclient import TestClient

    from main import app

    client = TestClient(app)
    # Host loopback (testserver está permitido) → pasa
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health", headers={"Host": "localhost:7777"}).status_code == 200
    # Host de un dominio externo (DNS-rebinding) → 403
    assert client.get("/api/health", headers={"Host": "evil.com"}).status_code == 403

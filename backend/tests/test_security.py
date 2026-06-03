"""Tests de endurecimiento: host confiable de descargas + defensa DNS-rebinding."""
import pytest

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


def test_judge_base_url_ssrf_rejected():
    # El juez API lleva la API key en Authorization → su base_url no puede apuntar a
    # metadatos cloud ni a la red interna (mismo allowlist anti-SSRF que base_url).
    from core.benchmark import BenchmarkRequest

    with pytest.raises(ValueError):
        BenchmarkRequest(
            model="m", engine="openai",
            judge={"mode": "api", "engine": "openai", "base_url": "http://169.254.169.254/latest"},
        )
    # Loopback y una API cloud conocida sí se aceptan; sin base_url cae al default seguro.
    BenchmarkRequest(model="m", engine="openai",
                     judge={"mode": "api", "engine": "openai", "base_url": "http://localhost:8080"})
    BenchmarkRequest(model="m", engine="openai", judge={"mode": "api", "engine": "openai"})


def test_local_path_unc_rejected():
    # Una ruta UNC (\\host\share) abriría una conexión SMB saliente que filtra el hash NTLM.
    from core.benchmark import BenchmarkRequest

    with pytest.raises(ValueError):
        BenchmarkRequest(model="m", engine="llamacpp", local_path="\\\\evil-host\\share\\x.gguf")
    with pytest.raises(ValueError):
        BenchmarkRequest(model="m", engine="llamacpp", local_path="//evil-host/share/x.gguf")
    with pytest.raises(ValueError):
        BenchmarkRequest(model="m", engine="llamacpp", local_path="modelo.bin")  # no .gguf
    # Una ruta local .gguf normal pasa.
    BenchmarkRequest(model="m", engine="llamacpp", local_path="C:/models/m.gguf")

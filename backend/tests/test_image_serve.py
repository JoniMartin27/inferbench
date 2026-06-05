"""Tests de la capa de generación de IMAGEN (stable-diffusion.cpp) en Serve/MCP.

Ligeros, SIN binario sd.cpp real ni red: validan el contrato HTTP de /api/serve/generate
(409 sin modelo de imagen, forma de la respuesta), el schema del catálogo (campo
modality + auxiliares), el registro del motor 'stablediffusion' y que la tool MCP
generate_image existe y devuelve ImageContent.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from core import serve as serve_core
from core.models_catalog import HfGguf, ImageSpec, Model, get_model, load_models
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_manager():
    mgr = serve_core.get_manager()
    mgr.model_id = None
    mgr.engine = None
    mgr.quant = None
    mgr.context = None
    mgr.modality = "text"
    mgr.phase = "idle"
    mgr.progress = None
    mgr.message = "Sin modelo servido."
    mgr._task = None
    yield
    mgr.phase = "idle"
    mgr.modality = "text"
    mgr.model_id = None
    mgr.engine = None


# --- contrato HTTP /api/serve/generate --------------------------------------

_GENERATE_KEYS = {
    "image_b64",
    "model_id",
    "seed",
    "width",
    "height",
    "steps",
    "elapsed_s",
    "phase",
    "message",
}


def test_generate_without_image_model_returns_409():
    r = client.post("/api/serve/generate", json={"prompt": "un gato astronauta"})
    assert r.status_code == 409
    assert "imagen" in r.json()["detail"].lower()


def test_generate_requires_prompt():
    r = client.post("/api/serve/generate", json={"prompt": "   "})
    assert r.status_code == 400


def test_status_includes_modality():
    body = client.get("/api/serve/status").json()
    assert "modality" in body
    assert body["modality"] == "text"


@pytest.mark.anyio
async def test_generate_raises_serve_error_when_text_model_loaded():
    """Si hay un modelo de TEXTO ready, generate() da 409 (no es de imagen)."""
    mgr = serve_core.get_manager()
    mgr.modality = "text"
    mgr.phase = "ready"
    with pytest.raises(serve_core.ServeError) as exc:
        await mgr.generate(prompt="hola")
    assert exc.value.status_code == 409


@pytest.mark.anyio
async def test_generate_proxies_to_sd_server(monkeypatch):
    """Con un modelo de imagen ready y el server vivo, generate() proxya a sd.cpp y
    devuelve el contrato completo (imagen como data URL)."""
    mgr = serve_core.get_manager()
    mgr.modality = "image"
    mgr.phase = "ready"
    mgr.engine = "stablediffusion"
    mgr.model_id = "sd-turbo"
    monkeypatch.setattr(mgr, "_engine_running", lambda: True)

    class _Resp:
        status_code = 200

        def json(self):
            return {"images": ["QUJD"], "info": ""}  # base64 PNG falso

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            assert url.endswith("/sdapi/v1/txt2img")
            assert json["prompt"] == "un gato"
            assert json["steps"] == 4
            return _Resp()

    monkeypatch.setattr(serve_core.httpx, "AsyncClient", _Client)
    out = await mgr.generate(prompt="un gato", steps=4, width=512, height=512, seed=7)
    assert set(out) == _GENERATE_KEYS
    assert out["image_b64"].startswith("data:image/png;base64,")
    assert out["seed"] == 7
    assert out["steps"] == 4
    assert out["model_id"] == "sd-turbo"
    assert isinstance(out["elapsed_s"], (int, float))


# --- schema del catálogo ----------------------------------------------------


def test_model_schema_accepts_modality_and_aux():
    m = Model(
        id="x",
        name="X",
        family="flux",
        params_b=12.0,
        active_b=12.0,
        is_moe=False,
        size_base_gb=7.5,
        max_ctx=0,
        modality="image",
        hf_gguf=HfGguf(
            repo="r/r",
            file_template="diff.gguf",
            diffusion_model="diff.gguf",
            vae="ae.safetensors",
            clip_l="clip_l.safetensors",
            t5xxl="t5.gguf",
        ),
        image=ImageSpec(default_steps=4, default_size=(1024, 1024), default_cfg_scale=1.0),
    )
    assert m.is_image is True
    assert m.modality == "image"
    assert m.hf_gguf.aux_files == {
        "diffusion_model": "diff.gguf",
        "vae": "ae.safetensors",
        "clip_l": "clip_l.safetensors",
        "t5xxl": "t5.gguf",
    }


def test_modality_defaults_to_text():
    m = Model(
        id="t",
        name="T",
        family="llama",
        params_b=1.0,
        active_b=1.0,
        is_moe=False,
        size_base_gb=2.0,
        max_ctx=4096,
    )
    assert m.modality == "text"
    assert m.is_image is False


def test_catalog_has_image_models():
    ids = {m.id for m in load_models()}
    assert "sd-turbo" in ids
    assert "flux.1-schnell-q4" in ids
    sd = get_model("sd-turbo")
    assert sd is not None and sd.is_image
    assert sd.hf_gguf.file == "sd_turbo.safetensors"
    flux = get_model("flux.1-schnell-q4")
    assert flux is not None and flux.is_image
    assert flux.hf_gguf.diffusion_model
    assert "vae" in flux.hf_gguf.aux_files


# --- motor stablediffusion --------------------------------------------------


def test_stablediffusion_engine_registered():
    from engines.registry import get_engine

    eng = get_engine("stablediffusion")
    assert eng.meta.id == "stablediffusion"
    assert eng.meta.default_port == 7861
    assert eng.meta.type == "local"


def test_stablediffusion_native_args_single_file():
    from engines.base import StartRequest
    from engines.registry import get_engine

    eng = get_engine("stablediffusion")
    args = eng.native_args(
        StartRequest(port=7861, engine_opts={"model": "/m/sd_turbo.safetensors"})
    )
    assert "--listen-port" in args and "7861" in args
    assert "-m" in args
    assert "/m/sd_turbo.safetensors" in args


def test_stablediffusion_native_args_flux_multifile():
    from engines.base import StartRequest
    from engines.registry import get_engine

    eng = get_engine("stablediffusion")
    args = eng.native_args(
        StartRequest(
            port=7861,
            engine_opts={
                "diffusion_model": "/m/flux.gguf",
                "vae": "/m/ae.safetensors",
                "clip_l": "/m/clip_l.safetensors",
                "t5xxl": "/m/t5.gguf",
                "offload_to_cpu": True,
                "diffusion_fa": True,
            },
        )
    )
    assert "--diffusion-model" in args
    assert "--vae" in args
    assert "--clip_l" in args
    assert "--t5xxl" in args
    assert "--offload-to-cpu" in args
    assert "--diffusion-fa" in args
    assert "-m" not in args  # FLUX usa diffusion-model, no checkpoint único


def test_engine_ports_include_stablediffusion():
    assert serve_core.ENGINE_PORTS.get("stablediffusion") == 7861
    assert serve_core.engine_endpoint("stablediffusion") == "http://127.0.0.1:7861"


# --- binary_manager variant matching ----------------------------------------


def test_sd_variant_terms_and_asset_match(monkeypatch):
    from core import binary_manager as bm

    # Forzar Windows + NVIDIA → debe pedir la build CUDA12.
    monkeypatch.setattr(bm.platform, "system", lambda: "Windows")

    class _Hw:
        gpus = [type("G", (), {"vendor": "nvidia"})()]

    monkeypatch.setattr("core.hardware.detect_hardware", lambda: _Hw())
    terms = bm._stablediffusion_variant_terms()
    assert "cuda12" in terms

    assets = [
        {"name": "sd-master-1f9ee88-bin-win-cuda12-x64.zip"},
        {"name": "sd-master-1f9ee88-bin-win-avx2-x64.zip"},
        {"name": "sd-master-1f9ee88-bin-win-vulkan-x64.zip"},
        {"name": "cudart-sd-bin-win-cu12-x64.zip"},
    ]
    chosen = bm._match_sd_asset(assets, terms)
    assert chosen is not None
    assert "cuda12" in chosen["name"]
    assert "cudart" not in chosen["name"]
    assert "vulkan" not in chosen["name"]


# --- MCP tool generate_image ------------------------------------------------


@pytest.mark.anyio
async def test_mcp_exposes_generate_image():
    import mcp_server

    server = mcp_server.get_server()
    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert "generate_image" in names
    # generate_video NO debe existir en esta fase.
    assert "generate_video" not in names


@pytest.mark.anyio
async def test_mcp_generate_image_returns_image_content(monkeypatch):
    import mcp_server

    async def fake_post(path, body=None):
        assert path == "/api/serve/generate"
        assert body["prompt"] == "un perro"
        return {
            "image_b64": "data:image/png;base64,QUJD",
            "model_id": "sd-turbo",
            "seed": 42,
            "width": 512,
            "height": 512,
            "steps": 4,
            "elapsed_s": 1.2,
            "phase": "ready",
            "message": "ok",
        }

    monkeypatch.setattr(mcp_server, "_post", fake_post)
    server = mcp_server.get_server()
    result = await server.call_tool("generate_image", {"prompt": "un perro"})
    # generate_image devuelve una lista PLANA de content blocks (ImageContent + TextContent),
    # no un string como chat. server.call_tool la propaga tal cual.
    blocks = list(result)
    kinds = {getattr(b, "type", None) for b in blocks}
    assert "image" in kinds  # debe haber un ImageContent para que el cliente lo muestre
    img = next(b for b in blocks if getattr(b, "type", None) == "image")
    assert img.data == "QUJD"  # base64 pelado (sin el prefijo data URL)
    assert img.mimeType == "image/png"
    text = "".join(getattr(b, "text", "") for b in blocks if getattr(b, "type", None) == "text")
    assert "seed 42" in text

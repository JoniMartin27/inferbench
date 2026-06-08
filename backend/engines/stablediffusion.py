"""Adaptador para stable-diffusion.cpp — generación de IMAGEN local (runtime nativo).

Hermano de llama.cpp para difusión (leejet/stable-diffusion.cpp). Igual que llamacpp.py
es la plantilla de un motor nativo: resuelve el binario `sd-server[.exe]` (descargado de
las releases de GitHub por binary_manager) y construye el comando del server HTTP de
sd.cpp, que expone APIs compatibles con OpenAI (/v1/images/generations) y AUTOMATIC1111
(/sdapi/v1/txt2img). InferBench orquesta este server por el modo Serve.

Modelos single-file (SD1.x/SDXL/SD-Turbo) cargan con `-m`. Modelos multi-archivo (FLUX)
necesitan `--diffusion-model` + auxiliares (`--vae`, `--clip_l`, `--t5xxl`), que el
ServeManager pasa por `engine_opts`.
"""
from __future__ import annotations

from pathlib import Path

from core import binary_manager

from .base import Engine, EngineMeta, ProgressCb, StartRequest

# Puerto del server sd.cpp (distinto del 8080 de llama-server). sd.cpp escucha por
# defecto en 1234; lo fijamos a 7861 para no colisionar con el slot de texto.
SD_SERVER_PORT = 7861


class StableDiffusionEngine(Engine):
    def __init__(self) -> None:
        super().__init__(
            EngineMeta(
                id="stablediffusion",
                name="stable-diffusion.cpp",
                type="local",
                default_port=SD_SERVER_PORT,
                image=None,  # solo runtime nativo por ahora (binario CUDA precompilado)
                optimizable=False,  # sin schema de optimización (no es benchmark de texto)
                description=(
                    "Servidor stable-diffusion.cpp para generación de imagen local "
                    "(GGUF/safetensors). Soporta SD1.x/SDXL single-file y FLUX multi-archivo. "
                    "Vídeo (Wan2.1/LTX): próximamente."
                ),
                runtimes=["native"],
                default_runtime="native",
            )
        )

    def build_command(self, req: StartRequest) -> list[str]:
        """sd.cpp solo corre nativo aquí; Docker no está soportado."""
        raise NotImplementedError(
            "stablediffusion solo soporta runtime nativo (binario precompilado de GitHub)"
        )

    def native_args(self, req: StartRequest) -> list[str]:
        """Args para el server `sd-server` nativo.

        El modelo y los auxiliares vienen en `engine_opts` (rutas absolutas resueltas por
        el ServeManager tras descargarlos de HF). Single-file → `-m`; multi-archivo (FLUX)
        → `--diffusion-model` + `--vae`/`--clip_l`/`--t5xxl`.
        """
        opts = req.engine_opts or {}
        port = req.port or self.meta.default_port
        # Bind a 0.0.0.0 para que el proxy del backend (127.0.0.1) lo alcance; el middleware
        # anti-DNS-rebinding del propio FastAPI sigue protegiendo la superficie pública.
        cmd: list[str] = ["--listen-ip", "0.0.0.0", "--listen-port", str(int(port))]

        diffusion_model = opts.get("diffusion_model") or opts.get("diffusionModel")
        model_path = opts.get("model") or req.model_path
        if diffusion_model:
            # FLUX y modelos con diffusion-model standalone.
            cmd += ["--diffusion-model", str(diffusion_model)]
        elif model_path:
            # SD1.x/SDXL/SD-Turbo: checkpoint único.
            cmd += ["-m", str(model_path)]

        vae = opts.get("vae")
        if vae:
            cmd += ["--vae", str(vae)]
        clip_l = opts.get("clip_l") or opts.get("clipL")
        if clip_l:
            cmd += ["--clip_l", str(clip_l)]
        clip_g = opts.get("clip_g") or opts.get("clipG")
        if clip_g:
            cmd += ["--clip_g", str(clip_g)]
        t5xxl = opts.get("t5xxl")
        if t5xxl:
            cmd += ["--t5xxl", str(t5xxl)]

        # GPU: sd.cpp usa todas las capas en GPU por defecto en builds CUDA. --offload-to-cpu
        # baja la presión de VRAM (recomendado para FLUX en 8 GB). Flash-attn de difusión
        # acelera y ahorra VRAM.
        if opts.get("offloadToCpu") or opts.get("offload_to_cpu"):
            cmd += ["--offload-to-cpu"]
        if opts.get("diffusionFa") or opts.get("diffusion_fa"):
            cmd += ["--diffusion-fa"]

        # CFG por defecto del pipeline (FLUX-schnell quiere cfg-scale 1.0); el valor por
        # petición lo manda el cliente en /sdapi/v1/txt2img.
        cfg = opts.get("cfgScale") or opts.get("cfg_scale")
        if cfg is not None:
            cmd += ["--cfg-scale", str(float(cfg))]

        return cmd

    def native_exe(self):
        async def _ensure(progress: ProgressCb = None) -> Path:
            return await binary_manager.install_stablediffusion(progress=progress)

        return _ensure

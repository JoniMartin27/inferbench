"""Modo Serve: sirve un modelo cuantizado de forma RESIDENTE y lo expone por la API
OpenAI del motor (llama.cpp → http://127.0.0.1:8080/v1).

Reutiliza la MISMA tubería que el benchmark: optimizer (quant/ctx/flags óptimos),
binary_manager (binario llama.cpp), model_manager (descarga GGUF) y native_runtime
(arranque del subprocess). A diferencia del benchmark, el motor queda corriendo y se
enruta la inferencia hacia él vía un proxy de chat simple (no-stream).

Slot ÚNICO: un solo modelo servido a la vez (igual que el patrón _LOADED de
native_runtime). La carga corre en background (asyncio.create_task) para no bloquear
el endpoint; el estado de fase/progreso se consulta vía status().
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Literal

import httpx
import psutil
from loguru import logger

from . import binary_manager, compat, model_manager, native_runtime
from .hardware import HardwareInfo, detect_hardware
from .models_catalog import get_model
from .optimizer import (
    _estimate_moe_offload,
    get_optimal_config,
    plan_llamacpp_run,
)

# Endpoint del motor servido. Texto: llamacpp nativo (8080, API OpenAI /v1).
# Imagen: stable-diffusion.cpp nativo (7861, API A1111 /sdapi/v1 + OpenAI /v1/images).
ENGINE_PORTS: dict[str, int] = {"llamacpp": 8080, "stablediffusion": 7861}

# Motor por defecto según la modalidad del modelo (el frontend puede sobreescribir).
DEFAULT_ENGINE_BY_MODALITY: dict[str, str] = {"text": "llamacpp", "image": "stablediffusion"}

Phase = Literal["idle", "downloading", "starting", "ready", "error"]


def engine_endpoint(engine: str) -> str:
    """Base URL OpenAI del motor (sin /v1)."""
    port = ENGINE_PORTS.get(engine, 8080)
    return f"http://127.0.0.1:{port}"


async def _wait_engine_ready(base_url: str, timeout: float = 120.0) -> None:
    """Espera a que el endpoint /v1/models del motor responda 200."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    last_err: str | None = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        while loop.time() < deadline:
            try:
                r = await client.get(f"{base_url.rstrip('/')}/v1/models")
                if r.status_code == 200:
                    return
                last_err = f"HTTP {r.status_code}"
            except Exception as e:  # noqa: BLE001 — el motor aún no escucha
                last_err = str(e)
            await asyncio.sleep(1.0)
    raise RuntimeError(f"El motor no quedó listo tras {timeout:.0f}s ({last_err})")


class ServeError(Exception):
    """Error de servicio (p.ej. no hay modelo ready). El router lo mapea a HTTP."""

    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ServeManager:
    """Estado del slot único de Serve + ciclo de vida del motor residente.

    Thread-safety: un asyncio.Lock serializa load()/unload() para que dos cargas no
    peleen por el slot del motor. chat()/status() no necesitan el lock (solo leen
    estado o hacen proxy de red).
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        # Estado del slot servido. None cuando está idle.
        self.model_id: str | None = None
        self.engine: str | None = None
        self.quant: str | None = None
        self.context: int | None = None
        self.modality: str = "text"  # "text" (chat) | "image" (generate)
        self.phase: Phase = "idle"
        self.progress: float | None = None
        self.message: str = "Sin modelo servido."
        self._hw: HardwareInfo | None = None

    # --- estado / serialización -------------------------------------------------

    @property
    def endpoint(self) -> str | None:
        if self.engine and self.phase in ("starting", "ready"):
            return f"{engine_endpoint(self.engine)}/v1"
        return None

    def _engine_running(self) -> bool:
        if not self.engine:
            return False
        try:
            return native_runtime.status(self.engine).state == "running"
        except Exception:  # noqa: BLE001
            return False

    def status_dict(self) -> dict[str, Any]:
        """Estado actual del slot según el CONTRATO HTTP.

        Si el proceso del motor murió por su cuenta (crash) reflejamos 'error'.
        """
        phase = self.phase
        if phase == "ready" and not self._engine_running():
            phase = "error"
            self.phase = "error"
            self.message = "El proceso del motor terminó inesperadamente."
        served = phase == "ready" and self.model_id is not None
        return {
            "served": served,
            "model_id": self.model_id,
            "engine": self.engine,
            "quant": self.quant,
            "context": self.context,
            "modality": self.modality,
            "endpoint": self.endpoint if phase in ("ready", "starting") else None,
            "phase": phase,
            "progress": self.progress,
            "message": self.message,
        }

    # --- carga ------------------------------------------------------------------

    async def _cancel_pending_task(self) -> None:
        """Cancela y espera la tarea de carga en background previa, si sigue viva.

        Sin esto, una segunda llamada a load()/_load_image() mientras la primera
        sigue descargando/arrancando sustituye la referencia a `self._task` y la
        deja huérfana: sigue corriendo sin lock, puede arrancar su motor DESPUÉS
        del nuevo (pisándolo en el mismo slot/puerto) y unload() ya no puede
        cancelarla. Debe llamarse con `self._lock` ya adquirido.
        """
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            # CancelledError hereda de BaseException (no de Exception) desde 3.8: hay que
            # capturarla explícitamente o la propia cancelación que acabamos de pedir se
            # propaga sin querer. Esperado: la cancelación misma o un fallo previo de la tarea.
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def load(
        self,
        model_id: str,
        engine: str = "llamacpp",
        quant: str | None = None,
        context: int | None = None,
    ) -> dict[str, Any]:
        """Empieza a servir un modelo de forma residente SIN bloquear.

        Valida el request, resuelve quant/ctx óptimos si vienen en None, deja el slot
        en fase 'downloading' y lanza la carga real en background. Devuelve el estado
        inicial inmediatamente. Si ya está servido el MISMO model+quant+engine ready,
        reusa el motor y responde 'ready' sin reiniciar.

        Discrimina por modalidad: los modelos modality="image" se sirven con
        stable-diffusion.cpp (slot único, mismo binario=un slot de GPU), no con llama-server.
        """
        # Rechazo temprano de motores no soportados en Serve (antes del lookup del modelo),
        # para que un engine inválido dé 400 aunque el modelo no exista.
        if engine not in ENGINE_PORTS:
            raise ServeError(
                f"Motor '{engine}' no soportado en modo Serve (soportados: "
                f"{', '.join(ENGINE_PORTS)}).",
                status_code=400,
            )
        model = get_model(model_id)
        if model is None:
            raise ServeError(f"Modelo desconocido: {model_id}", status_code=404)
        if not model.hf_gguf:
            raise ServeError(
                f"El modelo {model_id} no tiene fuente en HuggingFace; no se puede "
                f"auto-descargar para servirlo.",
                status_code=400,
            )

        # Auto-selección de motor por modalidad: si el caller deja el default 'llamacpp'
        # pero el modelo es de imagen, conmutamos a stablediffusion (y viceversa no aplica).
        if model.is_image and engine == "llamacpp":
            engine = DEFAULT_ENGINE_BY_MODALITY["image"]
        # El motor de imagen solo sirve modelos de imagen y al revés.
        if model.is_image and engine != "stablediffusion":
            raise ServeError(
                f"El modelo {model_id} es de imagen; sírvelo con el motor "
                f"'stablediffusion', no '{engine}'.",
                status_code=400,
            )
        if not model.is_image and engine == "stablediffusion":
            raise ServeError(
                f"El motor 'stablediffusion' solo sirve modelos de imagen; {model_id} es de texto.",
                status_code=400,
            )

        if model.is_image:
            return await self._load_image(model_id, engine)

        async with self._lock:
            # Resolver quant/ctx óptimos cuando vienen en None (misma lógica que el bench).
            self._hw = detect_hardware()
            optimal = get_optimal_config(engine, model_id, self._hw)
            if not optimal.feasible:
                raise ServeError(
                    f"Ninguna configuración de {model_id} cabe en este hardware. "
                    + (optimal.rationale[-1] if optimal.rationale else ""),
                    status_code=400,
                )
            chosen_quant = quant or optimal.quant or "Q4_K_M"

            # ¿Ya servimos exactamente esto y está vivo? → reusar sin reiniciar. Si el
            # caller pide un `context` explícito distinto del ya servido, NO reusamos:
            # honramos el nuevo valor reiniciando el motor (si no, un segundo load() con
            # otro `context` se ignoraría en silencio y serviría con el ctx viejo).
            if (
                self.phase == "ready"
                and self.model_id == model_id
                and self.engine == engine
                and self.quant == chosen_quant
                and (context is None or context == self.context)
                and self._engine_running()
            ):
                logger.info(f"serve: reusando motor ya cargado {model_id}/{chosen_quant}")
                return self.status_dict()

            # Plan de arranque para el quant REAL (ctx/ngl correctos, no los del óptimo).
            snap = compat.HardwareSnapshot(vram_gb=self._hw.primary_vram_gb, ram_gb=self._hw.ram_gb)
            kv = optimal.kv_cache or "f16"
            moe = optimal.moe_offload
            if moe and model.is_moe:
                moe = _estimate_moe_offload(model, snap, chosen_quant) or moe
            planned_ctx, ngl, ngl_mode = plan_llamacpp_run(
                model, snap, quant=chosen_quant, kv_k=kv, kv_v=kv, moe_offload=moe
            )
            chosen_ctx = int(context) if context else planned_ctx

            # Si había otra carga en curso (downloading/starting), cancelarla antes de
            # sustituir self._task — si no, queda huérfana corriendo en background.
            await self._cancel_pending_task()

            # Si había otro modelo servido, lo paramos antes de cargar el nuevo (slot único).
            # stop() es bloqueante (puede esperar hasta ~7s a que el proceso termine) →
            # se descarga a un hilo para no congelar el event loop mientras se sostiene el lock.
            if self.engine and self._engine_running():
                logger.info("serve: parando motor previo antes de cargar el nuevo")
                await asyncio.to_thread(native_runtime.stop, self.engine)
                native_runtime.set_loaded(self.engine, None)

            # Fijar el slot en 'downloading' y lanzar la carga real en background.
            self.model_id = model_id
            self.engine = engine
            self.quant = chosen_quant
            self.context = chosen_ctx
            self.modality = "text"
            self.phase = "downloading"
            self.progress = None
            self.message = "Preparando motor y modelo…"

            self._task = asyncio.create_task(
                self._run_load(model_id, engine, chosen_quant, chosen_ctx, kv, ngl, ngl_mode, moe)
            )
            return self.status_dict()

    async def _run_load(
        self,
        model_id: str,
        engine: str,
        quant: str,
        ctx: int,
        kv: str,
        ngl: int,
        ngl_mode: str,
        moe: int | None,
    ) -> None:
        """Tarea en background: binario → GGUF → arranque del motor → espera ready."""
        try:
            model = get_model(model_id)
            assert model is not None  # ya validado en load()

            # 1. Binario nativo (+ DLLs CUDA). Idempotente: solo baja lo que falte.
            self.phase = "downloading"
            self.message = "Preparando binario de llama.cpp…"

            async def bin_progress(evt: dict) -> None:
                self.progress = evt.get("pct")
                self.message = f"Binario: {evt.get('phase', 'descargando')}"

            if not binary_manager.llamacpp_fully_installed():
                await binary_manager.install_llamacpp(progress=bin_progress)
            binary = binary_manager.llamacpp_binary_path()

            # 2. GGUF del modelo (auto-descarga desde HF). Idempotente vía caché.
            self.message = f"Descargando GGUF {quant}…"

            async def model_progress(evt: dict) -> None:
                pct = evt.get("pct")
                if pct is not None:
                    self.progress = pct
                self.message = f"Descargando modelo {quant} ({pct or 0:.0f}%)"

            if not model_manager.gguf_installed(model, quant):
                await model_manager.ensure_gguf(model, quant, progress=model_progress)
            gguf_path = model_manager.gguf_path(model, quant)

            # Visión: projector mmproj (falla suave → corre como texto).
            mmproj_path = None
            try:
                if model.hf_gguf and model.hf_gguf.mmproj:
                    if model_manager.mmproj_installed(model):
                        mmproj_path = model_manager.mmproj_path(model)
                    else:
                        mmproj_path = await model_manager.ensure_mmproj(model)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"serve: mmproj falló ({e}); el modelo correrá como texto")
                mmproj_path = None

            # 3. Arranque del motor residente (mismo patrón que el bootstrap del bench).
            self.phase = "starting"
            self.progress = None
            self.message = "Arrancando el motor…"

            n_threads = max(2, psutil.cpu_count(logical=False) or 4)
            port = ENGINE_PORTS[engine]
            args = [
                "--host",
                "0.0.0.0",
                "--port",
                str(port),
                "-m",
                str(gguf_path),
                "--alias",
                model.id,
                "-c",
                str(ctx),
                "-ngl",
                str(ngl),
                "-ctk",
                kv,
                "-ctv",
                kv,
                "-t",
                str(n_threads),
                # Serve siempre activa flash attention (default del optimizer para llamacpp,
                # y obligatorio si la KV va cuantizada, kv != "f16"); a diferencia del bench,
                # aquí no hay overrides de engine_opts por request que puedan desactivarlo.
                "-fa",
                "on",
            ]
            if mmproj_path:
                args += ["--mmproj", str(mmproj_path)]
            if moe:
                args += ["--n-cpu-moe", str(moe)]

            logger.info(f"serve start [{engine}]: ctx={ctx} ngl={ngl} ({ngl_mode}) quant={quant}")
            native_runtime.start(engine, exe=binary, args=args, port=port)
            native_runtime.set_loaded(
                engine,
                {
                    "model": model.id,
                    "quant": quant,
                    "ctx": ctx,
                    "mmproj": bool(mmproj_path),
                    "served": True,
                },
            )

            self.message = "Esperando a que el motor responda…"
            await _wait_engine_ready(engine_endpoint(engine), timeout=120.0)

            self.phase = "ready"
            self.progress = 100.0
            self.message = f"Sirviendo {model_id} ({quant}) en {self.endpoint}"
            logger.success(f"serve: {model_id}/{quant} listo en {self.endpoint}")
        except asyncio.CancelledError:
            # Una carga en curso puede cancelarse desde _cancel_pending_task() (otra
            # load() la sustituye) o desde unload(). En ambos casos, si el motor ya
            # había arrancado, hay que pararlo aquí mismo: `engine` es el parámetro de
            # ESTA tarea, no self.engine (que para entonces puede ya apuntar al nuevo).
            self.phase = "error"
            self.message = "Carga cancelada."
            try:
                if engine:
                    await asyncio.to_thread(native_runtime.stop, engine)
                    native_runtime.set_loaded(engine, None)
            except Exception:  # noqa: BLE001
                pass
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("serve: fallo al cargar el modelo")
            self.phase = "error"
            self.progress = None
            self.message = f"Error al servir el modelo: {e}"
            try:
                if engine:
                    await asyncio.to_thread(native_runtime.stop, engine)
                    native_runtime.set_loaded(engine, None)
            except Exception:  # noqa: BLE001
                pass

    # --- carga de imagen (stable-diffusion.cpp) ---------------------------------

    async def _load_image(self, model_id: str, engine: str) -> dict[str, Any]:
        """Variante de load() para modelos de imagen. No usa el optimizer de texto:
        sd.cpp no tiene quant/ctx/ngl; el slot único sigue siendo válido (un binario en
        GPU). Lanza la carga en background y devuelve el estado inicial."""
        async with self._lock:
            model = get_model(model_id)
            assert model is not None

            # ¿Ya servimos exactamente esto y está vivo? → reusar sin reiniciar.
            if (
                self.phase == "ready"
                and self.model_id == model_id
                and self.engine == engine
                and self._engine_running()
            ):
                logger.info(f"serve: reusando server de imagen ya cargado {model_id}")
                return self.status_dict()

            # Si había otra carga en curso, cancelarla antes de sustituir self._task.
            await self._cancel_pending_task()

            # Parar el motor previo (texto o imagen) — slot único de GPU. stop() bloquea
            # (hasta ~7s) → a un hilo para no congelar el event loop con el lock tomado.
            if self.engine and self._engine_running():
                logger.info("serve: parando motor previo antes de cargar el de imagen")
                await asyncio.to_thread(native_runtime.stop, self.engine)
                native_runtime.set_loaded(self.engine, None)

            self.model_id = model_id
            self.engine = engine
            self.quant = None
            self.context = None
            self.modality = "image"
            self.phase = "downloading"
            self.progress = None
            self.message = "Preparando stable-diffusion.cpp y el modelo…"

            self._task = asyncio.create_task(self._run_load_image(model_id, engine))
            return self.status_dict()

    async def _run_load_image(self, model_id: str, engine: str) -> None:
        """Tarea en background: binario sd.cpp → checkpoint/auxiliares → arranque del server."""
        try:
            model = get_model(model_id)
            assert model is not None and model.hf_gguf is not None

            # 1. Binario sd-server (+ DLLs CUDA). Idempotente.
            self.phase = "downloading"
            self.message = "Preparando binario de stable-diffusion.cpp…"

            async def bin_progress(evt: dict) -> None:
                self.progress = evt.get("pct")
                self.message = f"Binario sd.cpp: {evt.get('phase', 'descargando')}"

            if not binary_manager.stablediffusion_fully_installed():
                await binary_manager.install_stablediffusion(progress=bin_progress)
            binary = binary_manager.stablediffusion_binary_path()

            # 2. Modelo + auxiliares desde HF (idempotente vía caché).
            async def model_progress(evt: dict) -> None:
                pct = evt.get("pct")
                if pct is not None:
                    self.progress = pct
                self.message = f"Descargando {evt.get('kind', 'modelo')} ({pct or 0:.0f}%)"

            opts: dict[str, Any] = {}
            gg = model.hf_gguf
            if gg.diffusion_model:
                # FLUX (multi-archivo): diffusion-model + auxiliares.
                self.message = "Descargando diffusion-model y auxiliares…"
                aux = await model_manager.ensure_all_aux(model, progress=model_progress)
                if "diffusion_model" not in aux:
                    raise RuntimeError(f"No se pudo obtener el diffusion-model de {model_id}")
                opts["diffusion_model"] = str(aux["diffusion_model"])
                for kind in ("vae", "clip_l", "clip_g", "t5xxl"):
                    if kind in aux:
                        opts[kind] = str(aux[kind])
            else:
                # SD1.x/SDXL/SD-Turbo single-file.
                self.message = "Descargando checkpoint…"
                ckpt = await model_manager.ensure_single_file(model, progress=model_progress)
                if ckpt is None:
                    raise RuntimeError(
                        f"El modelo {model_id} no declara checkpoint (`file`) ni diffusion-model"
                    )
                opts["model"] = str(ckpt)

            # Defaults de arranque del pipeline (cfg/offload/flash-attn) desde el catálogo.
            spec = model.image
            if spec:
                opts["cfg_scale"] = spec.default_cfg_scale
                if spec.offload_to_cpu:
                    opts["offload_to_cpu"] = True
                if spec.diffusion_fa:
                    opts["diffusion_fa"] = True

            # 3. Arrancar el server sd.cpp con los args del engine.
            self.phase = "starting"
            self.progress = None
            self.message = "Arrancando stable-diffusion.cpp…"

            from engines.base import StartRequest
            from engines.registry import get_engine

            sd_engine = get_engine(engine)
            port = ENGINE_PORTS[engine]
            req = StartRequest(port=port, gpu=True, engine_opts=opts)
            args = sd_engine.native_args(req)

            logger.info(f"serve start [image/{engine}]: {model_id} opts={list(opts)}")
            native_runtime.start(engine, exe=binary, args=args, port=port)
            native_runtime.set_loaded(
                engine,
                {"model": model.id, "modality": "image", "served": True},
            )

            self.message = "Esperando a que el server de imagen responda…"
            await _wait_engine_ready(engine_endpoint(engine), timeout=180.0)

            self.phase = "ready"
            self.progress = 100.0
            self.message = f"Sirviendo {model_id} (imagen) en {self.endpoint}"
            logger.success(f"serve: {model_id} (imagen) listo en {self.endpoint}")
        except asyncio.CancelledError:
            # Igual que en _run_load: si el motor ya había arrancado cuando llegó la
            # cancelación (sustitución por otra load() o unload()), pararlo aquí.
            self.phase = "error"
            self.message = "Carga cancelada."
            try:
                if engine:
                    await asyncio.to_thread(native_runtime.stop, engine)
                    native_runtime.set_loaded(engine, None)
            except Exception:  # noqa: BLE001
                pass
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("serve: fallo al cargar el modelo de imagen")
            self.phase = "error"
            self.progress = None
            self.message = f"Error al servir el modelo de imagen: {e}"
            try:
                if engine:
                    await asyncio.to_thread(native_runtime.stop, engine)
                    native_runtime.set_loaded(engine, None)
            except Exception:  # noqa: BLE001
                pass

    # --- generate (proxy a sd.cpp) ----------------------------------------------

    async def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        steps: int = 20,
        width: int = 512,
        height: int = 512,
        seed: int = -1,
        cfg_scale: float = 7.0,
        sampler: str | None = None,
    ) -> dict[str, Any]:
        """Genera una imagen vía el server sd.cpp servido. 409 si no hay modelo de imagen
        ready. Proxy a /sdapi/v1/txt2img (A1111-compat, JSON-in/JSON-out); devuelve la
        imagen como data URL PNG base64.
        """
        if self.modality != "image":
            raise ServeError(
                "No hay ningún modelo de IMAGEN servido. Carga uno con /api/serve/load "
                "(modelo modality='image') y espera a la fase 'ready'.",
                status_code=409,
            )
        if self.phase != "ready" or not self.endpoint:
            raise ServeError(
                "No hay ningún modelo de imagen servido y listo. Carga uno y espera a "
                "la fase 'ready'.",
                status_code=409,
            )
        if not self._engine_running():
            self.phase = "error"
            self.message = "El proceso del server de imagen terminó inesperadamente."
            raise ServeError("El server de imagen ya no está corriendo.", status_code=409)

        base = engine_endpoint(self.engine or "stablediffusion")
        url = f"{base}/sdapi/v1/txt2img"
        # Resolvemos -1 a una semilla CONCRETA aquí (no en sd.cpp): el endpoint A1111 de
        # sd.cpp NO devuelve la semilla efectiva (el campo `info` viene vacío y `parameters`
        # solo refleja la petición), así que si dejáramos pasar -1 nunca podríamos reportar
        # la semilla real y el resultado sería irreproducible. Elegirla nosotros es honesto
        # (no inventamos métricas: ES la semilla que de verdad usa la generación) y cumple el
        # contrato de reproducibilidad del frontend/MCP.
        effective_seed = int(seed)
        if effective_seed < 0:
            effective_seed = random.randint(0, 2**31 - 1)
        body: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": negative_prompt or "",
            "steps": int(steps),
            "width": int(width),
            "height": int(height),
            "seed": effective_seed,
            "cfg_scale": float(cfg_scale),
            "batch_size": 1,
        }
        if sampler:
            body["sampler_name"] = sampler

        loop = asyncio.get_event_loop()
        t0 = loop.time()
        try:
            # La generación es lenta (decenas de segundos en CPU/FLUX): timeout generoso.
            async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=10.0)) as client:
                resp = await client.post(url, json=body)
                if resp.status_code >= 400:
                    raise ServeError(
                        f"El server de imagen respondió HTTP {resp.status_code}: {resp.text[:300]}",
                        status_code=502,
                    )
                data = resp.json()
        except ServeError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ServeError(f"No se pudo contactar al server de imagen: {e}", status_code=502)

        elapsed = round(loop.time() - t0, 2)
        if not isinstance(data, dict):
            raise ServeError(
                "El server de imagen devolvió una respuesta con forma inesperada.",
                status_code=502,
            )
        images = data.get("images") or []
        if not images or not isinstance(images[0], str):
            raise ServeError("El server de imagen no devolvió ninguna imagen.", status_code=502)
        raw_b64 = images[0]
        # sd.cpp devuelve PNG base64 sin prefijo; el contrato pide data URL.
        image_b64 = raw_b64 if raw_b64.startswith("data:") else f"data:image/png;base64,{raw_b64}"
        return {
            "image_b64": image_b64,
            "model_id": self.model_id,
            "seed": effective_seed,
            "width": int(width),
            "height": int(height),
            "steps": int(steps),
            "elapsed_s": elapsed,
            "phase": self.phase,
            "message": "ok",
        }

    # --- chat (proxy) -----------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Proxy de chat (no-stream) al endpoint OpenAI del motor servido.

        Junta el texto y lo devuelve con usage/tps. Si no hay modelo ready → ServeError
        409 (lo mapea el router).
        """
        if self.modality == "image":
            raise ServeError(
                "El modelo servido es de IMAGEN; usa /api/serve/generate, no /chat.",
                status_code=409,
            )
        if self.phase != "ready" or not self.endpoint:
            raise ServeError(
                "No hay ningún modelo servido y listo. Carga uno con /api/serve/load "
                "y espera a la fase 'ready'.",
                status_code=409,
            )
        if not self._engine_running():
            self.phase = "error"
            self.message = "El proceso del motor terminó inesperadamente."
            raise ServeError("El motor servido ya no está corriendo.", status_code=409)

        url = f"{self.endpoint.rstrip('/')}/chat/completions"
        body = {
            "model": self.model_id,
            "messages": messages,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
                resp = await client.post(url, json=body)
                if resp.status_code >= 400:
                    raise ServeError(
                        f"El motor respondió HTTP {resp.status_code}: {resp.text[:300]}",
                        status_code=502,
                    )
                data = resp.json()
        except ServeError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ServeError(f"No se pudo contactar al motor servido: {e}", status_code=502)

        if not isinstance(data, dict):
            raise ServeError(
                "El motor servido devolvió una respuesta con forma inesperada.",
                status_code=502,
            )
        choices = data.get("choices") or [{}]
        choice = choices[0] if isinstance(choices[0], dict) else {}
        content = (choice.get("message") or {}).get("content", "") or ""
        usage = data.get("usage")
        # tok/s de decode: timings internos de llama-server si los expone.
        tps: float | None = None
        timings = data.get("timings") or {}
        if isinstance(timings, dict):
            tps = timings.get("predicted_per_second")
        return {
            "content": content,
            "model_id": self.model_id,
            "phase": self.phase,
            "usage": usage,
            "tps": tps,
            "message": "ok",
        }

    # --- unload -----------------------------------------------------------------

    async def unload(self) -> dict[str, Any]:
        """Para el motor servido y resetea el slot."""
        async with self._lock:
            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                # CancelledError hereda de BaseException, no de Exception (desde 3.8):
                # capturarla explícitamente, si no la cancelación que acabamos de pedir
                # se propaga y rompe unload(). Esperado: la cancelación u otro fallo previo.
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            engine = self.engine
            if engine:
                try:
                    await asyncio.to_thread(native_runtime.stop, engine)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"serve: error parando el motor: {e}")
                native_runtime.set_loaded(engine, None)
            self.model_id = None
            self.engine = None
            self.quant = None
            self.context = None
            self.modality = "text"
            self.phase = "idle"
            self.progress = None
            self.message = "Motor parado. Sin modelo servido."
            return {"served": False, "phase": "idle", "message": self.message}


# Instancia única del slot de Serve (mismo patrón de estado-módulo que native_runtime).
_MANAGER = ServeManager()


def get_manager() -> ServeManager:
    return _MANAGER

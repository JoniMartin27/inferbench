"""Cuánto cuesta de verdad cada cuantización, medido en esta máquina.

El resto de la app puntúa modelos con tareas (`core/benchmark.py`). Ese scorer NO sirve
para comparar cuantizaciones del MISMO modelo: sobre los 262 resultados guardados,
llama-3.2-1b puntúa 70,0 a Q4_K_M y 60,0 a Q8_0 —mejor a MENOR precisión— y gemma-2-9b sale
plano de IQ2_XS a IQ4_XS. Es ruido de prompt y de acierto/fallo, no señal: una tarea con
respuesta correcta se acierta o no, y eso satura mucho antes de que se note la degradación.

El instrumento estándar para esto es comparar la DISTRIBUCIÓN de salida contra el mismo
modelo a mayor precisión, y viene incluido en llama.cpp (`llama-perplexity`):

- **PPL(Q)/PPL(base)** — cuánto empeora la perplejidad. 1,01 = 1% peor.
- **KL divergence** — cuánto se separa la distribución completa de la de referencia.
  Es la métrica sensible: detecta daño mucho antes de que la perplejidad se mueva.
- **Same top p** — con qué frecuencia elige la MISMA palabra que la referencia. Es el
  número legible: «coincide con el original el 98% de las veces».

Se mide contra la mejor cuantización que haya descargada del mismo modelo, no contra un
ideal teórico: inferbench mide lo que tienes, no lo que debería haber.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from loguru import logger

from core.binary_manager import _llamacpp_dir

# Orden de calidad, de mayor a menor. Se usa para elegir la referencia: la mejor
# cuantización descargada del mismo modelo. Es el mismo orden que `optimizer.ENGINE_QUANTS`,
# ampliado con los formatos sin cuantizar que puede haber en disco.
ORDEN_CALIDAD = [
    "F32",
    "BF16",
    "F16",
    "Q8_0",
    "Q6_K",
    "Q5_K_M",
    "Q5_K_S",
    "Q4_K_M",
    "Q4_K_S",
    "IQ4_NL",
    "IQ4_XS",
    "Q3_K_L",
    "Q3_K_M",
    "Q3_K_S",
    "IQ3_M",
    "IQ3_S",
    "IQ3_XXS",
    "Q2_K",
    "IQ2_M",
    "IQ2_S",
    "IQ2_XS",
    "IQ2_XXS",
    "IQ1_M",
    "IQ1_S",
]

CTX_POR_DEFECTO = 512  # el que usa llama.cpp para publicar perplejidades comparables


def binario() -> Path:
    """Ruta de `llama-perplexity`. Viene en la misma release que `llama-server`."""
    nombre = "llama-perplexity.exe" if os.name == "nt" else "llama-perplexity"
    return _llamacpp_dir() / nombre


def instalado() -> bool:
    return binario().exists()


def corpus_por_defecto() -> Path:
    """Texto fijo y bilingüe (EN+ES) para que dos medidas sean comparables.

    La perplejidad depende MUCHÍSIMO del texto: medida sobre `context_haystack.txt`
    —sintético y repetitivo— da PPL 1,86 y comprime las diferencias entre cuantizaciones
    hasta hacerlas indistinguibles. Por eso hay un corpus propio de prosa real, y por eso
    es el MISMO siempre: cambiarlo invalida las comparaciones guardadas.
    """
    return Path(__file__).resolve().parent.parent / "data" / "quality_corpus.txt"


def _dir_logits() -> Path:
    base = (
        Path(os.environ["APPDATA"]) / "InferBench"
        if os.name == "nt" and "APPDATA" in os.environ
        else Path.home() / ".inferbench"
    )
    d = base / "kld"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _dir_datos() -> Path:
    base = (
        Path(os.environ["APPDATA"]) / "InferBench"
        if os.name == "nt" and "APPDATA" in os.environ
        else Path.home() / ".inferbench"
    )
    base.mkdir(parents=True, exist_ok=True)
    return base


def fichero_resultados() -> Path:
    """Dónde se guardan las comparaciones de daño por cuantización ya medidas."""
    return _dir_datos() / "quant_damage.json"


def cargar_resultados() -> list[dict]:
    f = fichero_resultados()
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        # Un fichero corrupto no puede tumbar una vista: se avisa y se sigue con lista vacía.
        logger.warning(f"quant_damage.json ilegible: {e}")
        return []


def guardar_resultado(comp: dict) -> None:
    datos = [c for c in cargar_resultados() if c.get("modelo") != comp.get("modelo")]
    datos.append(comp)
    fichero_resultados().write_text(
        json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def modelo_base_de_plantilla(file_template: str | None) -> str | None:
    """`Llama-3.2-1B-Instruct-{quant}.gguf` → `Llama-3.2-1B-Instruct`.

    Es el mismo nombre con el que se guardan las medidas (que salen del fichero GGUF de
    disco), así que sirve de puente entre el catálogo y lo ya medido.
    """
    if not file_template:
        return None
    nombre = file_template.replace("{quant}", "Q4_K_M")
    return _modelo_del_nombre(Path(nombre))


def dano_medido(modelo_base: str | None, quant: str | None) -> dict | None:
    """La medida real de daño de ESTE modelo a ESTE quant, si existe. None si no se ha medido.

    Devuelve `{referencia, same_top_pct, ppl_ratio, kld_media}`. Sirve para que la
    recomendación deje de apoyarse solo en la heurística de bits/peso cuando hay una
    medida de verdad: `same_top_pct` es el % de tokens en los que el modelo cuantizado
    elige el MISMO token más probable que la referencia.
    """
    if not modelo_base or not quant:
        return None
    objetivo = quant.upper()
    for comp in cargar_resultados():
        if comp.get("modelo") != modelo_base:
            continue
        for m in comp.get("medidas") or []:
            if (m.get("quant") or "").upper() != objetivo or m.get("error"):
                continue
            if m.get("es_referencia"):
                # La referencia no tiene daño CONTRA sí misma: decir 100% sería inventarse
                # una medida que nadie ha hecho.
                return {"referencia": comp.get("referencia"), "es_referencia": True}
            if m.get("same_top_pct") is None:
                return None
            return {
                "referencia": comp.get("referencia"),
                "es_referencia": False,
                "same_top_pct": m.get("same_top_pct"),
                "ppl_ratio": m.get("ppl_ratio"),
                "kld_media": m.get("kld_media"),
            }
    return None


def rango_calidad(quant: str) -> int:
    """Posición en `ORDEN_CALIDAD`; los desconocidos van al final (peor)."""
    q = (quant or "").upper()
    return ORDEN_CALIDAD.index(q) if q in ORDEN_CALIDAD else len(ORDEN_CALIDAD)


def elegir_referencia(quants: list[str]) -> str | None:
    """La mejor cuantización disponible, que es contra la que se compara todo lo demás."""
    return min(quants, key=rango_calidad) if quants else None


@dataclass
class MedidaCuant:
    """Lo que cuesta una cuantización frente a la referencia."""

    quant: str
    ppl: float | None = None
    # None en la propia referencia: no se compara consigo misma.
    ppl_ratio: float | None = None
    kld_media: float | None = None
    kld_p99: float | None = None
    same_top_pct: float | None = None
    rms_dp_pct: float | None = None
    chunks: int = 0
    segundos: float = 0.0
    es_referencia: bool = False
    error: str | None = None

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class ComparativaCuant:
    modelo: str
    referencia: str | None = None
    corpus: str = ""
    ctx: int = CTX_POR_DEFECTO
    chunks_pedidos: int = 0
    medidas: list[MedidaCuant] = field(default_factory=list)

    def dict(self) -> dict:
        return {**asdict(self), "medidas": [m.dict() for m in self.medidas]}


# ---------------------------------------------------------------- parseo de la salida

# `Final estimate: PPL = 1.8644 +/- 0.15509`
_RE_PPL = re.compile(r"Final estimate:\s*PPL\s*=\s*([0-9.]+)")
# `Mean PPL(Q)/PPL(base)         :   1.010562 ±   0.009773`  (el ± puede venir como +/-)
_RE_RATIO = re.compile(r"Mean PPL\(Q\)/PPL\(base\)\s*:\s*([0-9.]+)")
_RE_PPL_Q = re.compile(r"Mean PPL\(Q\)\s*:\s*([0-9.]+)")
_RE_KLD = re.compile(r"Mean\s+KLD:\s*(-?[0-9.]+)")
_RE_KLD_P99 = re.compile(r"99\.0%\s+KLD:\s*(-?[0-9.]+)")
_RE_SAME_TOP = re.compile(r"Same top p:\s*([0-9.]+)")
_RE_RMS_DP = re.compile(r"RMS\s+.p\s*:\s*([0-9.]+)")
# El progreso viene en DOS formatos según el modo, y esto no es un detalle: en modo KLD
# —que son las pasadas largas— no hay corchetes, sino filas de una tabla. Con un solo patrón
# la barra de progreso se quedaba clavada justo en las medidas que más tardan.
#   modo normal: `[1]1.8893,[2]1.8644,`
#   modo KLD:    `   1       1.9109 ±    0.2420       0.02192 ± …`
_RE_CHUNK = re.compile(r"\[(\d+)\]")
_RE_CHUNK_TABLA = re.compile(r"^\s*(\d+)\s+[0-9.]+\s+[±+]", re.MULTILINE)


def _chunks_vistos(texto: str) -> list[int]:
    return [int(n) for n in _RE_CHUNK.findall(texto)] + [
        int(n) for n in _RE_CHUNK_TABLA.findall(texto)
    ]


def _num(rx: re.Pattern, texto: str) -> float | None:
    m = rx.search(texto)
    return float(m.group(1)) if m else None


def parsear(salida: str, quant: str, *, es_referencia: bool = False) -> MedidaCuant:
    """Extrae las métricas de la salida de `llama-perplexity`.

    Se parsea texto porque la herramienta no tiene salida legible por máquina. Los
    formatos están fijados por los tests con salidas REALES capturadas de la herramienta,
    no inventadas: si una versión de llama.cpp cambia una etiqueta, el test canta.
    """
    m = MedidaCuant(quant=quant, es_referencia=es_referencia)
    # En modo KLD la perplejidad del quant sale como `Mean PPL(Q)`; en modo normal, como
    # `Final estimate`. Se acepta cualquiera de las dos.
    m.ppl = _num(_RE_PPL, salida) or _num(_RE_PPL_Q, salida)
    if not es_referencia:
        m.ppl_ratio = _num(_RE_RATIO, salida)
        m.kld_media = _num(_RE_KLD, salida)
        m.kld_p99 = _num(_RE_KLD_P99, salida)
        m.same_top_pct = _num(_RE_SAME_TOP, salida)
        m.rms_dp_pct = _num(_RE_RMS_DP, salida)
    m.chunks = max(_chunks_vistos(salida), default=0)
    return m


# ---------------------------------------------------------------- ejecución


async def _ejecutar(args: list[str], al_avanzar=None) -> tuple[int, str]:
    """Lanza llama-perplexity sin bloquear el event loop y va informando del progreso.

    La salida se lee en streaming (no `communicate()`) porque una medida seria son
    minutos: sin progreso el usuario ve la app colgada y la mata.
    """
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    trozos: list[str] = []
    ultimo = -1
    assert proc.stdout is not None
    while True:
        linea = await proc.stdout.readline()
        if not linea:
            break
        texto = linea.decode("utf-8", errors="replace")
        trozos.append(texto)
        if al_avanzar:
            nums = _chunks_vistos(texto)
            if nums:
                n = max(nums)
                if n > ultimo:
                    ultimo = n
                    al_avanzar(n)
    await proc.wait()
    return proc.returncode or 0, "".join(trozos)


def _clave_base(modelo: Path, corpus: Path, ctx: int, chunks: int) -> Path:
    """Los logits de referencia se cachean: recalcularlos es la mitad del coste total."""
    h = hashlib.sha256()
    h.update(str(modelo.resolve()).encode())
    h.update(str(modelo.stat().st_size).encode())
    h.update(corpus.read_bytes())
    h.update(f"{ctx}:{chunks}".encode())
    return _dir_logits() / f"{h.hexdigest()[:16]}.dat"


async def medir_referencia(
    modelo: Path,
    *,
    corpus: Path | None = None,
    ctx: int = CTX_POR_DEFECTO,
    chunks: int = 0,
    ngl: int = 0,
    al_avanzar=None,
) -> tuple[Path, MedidaCuant]:
    """Corre la referencia y guarda sus logits para poder comparar contra ellos."""
    corpus = corpus or corpus_por_defecto()
    destino = _clave_base(modelo, corpus, ctx, chunks)
    args = [
        str(binario()),
        "-m",
        str(modelo),
        "-f",
        str(corpus),
        "-c",
        str(ctx),
        "-ngl",
        str(ngl),
        "--kl-divergence-base",
        str(destino),
    ]
    if chunks > 0:
        args += ["--chunks", str(chunks)]

    if destino.exists():
        logger.info(f"logits de referencia ya cacheados: {destino.name}")

    t0 = time.perf_counter()
    codigo, salida = await _ejecutar(args, al_avanzar)
    medida = parsear(salida, _quant_del_nombre(modelo), es_referencia=True)
    medida.segundos = round(time.perf_counter() - t0, 1)
    if codigo != 0:
        medida.error = _ultimo_error(salida)
    return destino, medida


async def medir_contra(
    modelo: Path,
    base: Path,
    *,
    corpus: Path | None = None,
    ctx: int = CTX_POR_DEFECTO,
    chunks: int = 0,
    ngl: int = 0,
    al_avanzar=None,
) -> MedidaCuant:
    """Mide una cuantización contra los logits de referencia."""
    corpus = corpus or corpus_por_defecto()
    args = [
        str(binario()),
        "-m",
        str(modelo),
        "-f",
        str(corpus),
        "-c",
        str(ctx),
        "-ngl",
        str(ngl),
        "--kl-divergence",
        "--kl-divergence-base",
        str(base),
    ]
    if chunks > 0:
        args += ["--chunks", str(chunks)]

    t0 = time.perf_counter()
    codigo, salida = await _ejecutar(args, al_avanzar)
    medida = parsear(salida, _quant_del_nombre(modelo))
    medida.segundos = round(time.perf_counter() - t0, 1)
    if codigo != 0:
        medida.error = _ultimo_error(salida)
    return medida


async def comparar_quants(
    modelos: dict[str, Path],
    *,
    corpus: Path | None = None,
    ctx: int = CTX_POR_DEFECTO,
    chunks: int = 0,
    ngl: int = 0,
    al_evento=None,
) -> ComparativaCuant:
    """Mide todas las cuantizaciones de un modelo contra la mejor que haya en disco.

    `modelos` es `{quant: ruta}`. La referencia se mide primero (guarda sus logits) y el
    resto se compara contra ella. Se corre EN SERIE a propósito: dos procesos cargando
    pesos a la vez se pelean por la VRAM, que es justo el fallo que este proyecto ya
    documenta en `_start_docker`.
    """
    corpus = corpus or corpus_por_defecto()
    comp = ComparativaCuant(modelo="", corpus=corpus.name, ctx=ctx, chunks_pedidos=chunks)
    if not modelos:
        return comp

    ref = elegir_referencia(list(modelos))
    comp.referencia = ref
    comp.modelo = _modelo_del_nombre(modelos[ref])

    def emitir(tipo: str, **datos):
        if al_evento:
            al_evento({"type": tipo, **datos})

    emitir("start", referencia=ref, total=len(modelos))

    emitir("measuring", quant=ref, role="referencia")
    base, medida_ref = await medir_referencia(
        modelos[ref],
        corpus=corpus,
        ctx=ctx,
        chunks=chunks,
        ngl=ngl,
        al_avanzar=lambda n: emitir("progress", quant=ref, chunk=n),
    )
    comp.medidas.append(medida_ref)
    emitir("measured", **medida_ref.dict())

    if medida_ref.error:
        # Sin referencia no hay nada contra lo que comparar: parar es más honesto que
        # devolver medidas sueltas que el usuario creería comparables.
        emitir("error", detail=medida_ref.error)
        return comp

    for quant, ruta in sorted(modelos.items(), key=lambda kv: rango_calidad(kv[0])):
        if quant == ref:
            continue
        emitir("measuring", quant=quant, role="candidato")
        medida = await medir_contra(
            ruta,
            base,
            corpus=corpus,
            ctx=ctx,
            chunks=chunks,
            ngl=ngl,
            al_avanzar=lambda n, q=quant: emitir("progress", quant=q, chunk=n),
        )
        comp.medidas.append(medida)
        emitir("measured", **medida.dict())

    emitir("done", medidas=len(comp.medidas))
    return comp


_RE_MODELO = re.compile(r"^(.*?)[-.](?:(?:IQ|Q)\d[_A-Z0-9]*|F16|BF16|F32)\.gguf$", re.IGNORECASE)


def _modelo_del_nombre(ruta: Path) -> str:
    """`Llama-3.2-1B-Instruct-Q4_K_M.gguf` → `Llama-3.2-1B-Instruct`."""
    m = _RE_MODELO.match(ruta.name)
    return m.group(1) if m else ruta.stem


def _ultimo_error(salida: str) -> str:
    """La última línea con contenido suele llevar el motivo real del fallo."""
    lineas = [ln.strip() for ln in salida.splitlines() if ln.strip()]
    for ln in reversed(lineas):
        if "error" in ln.lower() or "failed" in ln.lower():
            return ln[:300]
    return lineas[-1][:300] if lineas else "llama-perplexity falló sin mensaje"


_RE_QUANT_NOMBRE = re.compile(
    r"[-.]((?:IQ|Q)\d[_A-Z0-9]*|F16|BF16|F32)(?=\.gguf$|[-.])", re.IGNORECASE
)


def _quant_del_nombre(ruta: Path) -> str:
    """`Llama-3.2-1B-Instruct-Q4_K_M.gguf` → `Q4_K_M`."""
    m = _RE_QUANT_NOMBRE.search(ruta.name)
    return m.group(1).upper() if m else "?"

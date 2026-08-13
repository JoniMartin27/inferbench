"""El Dashboard no puede recomendar de portada lo que la app nunca ha medido.

MEDIDO 2026-08-13 en una GPU de 8 GB: `/api/optimize/recommendations` devolvía **15 de 15
modelos por debajo de 3 bits por peso** (14× IQ1_S a 1,5 bits, 1× IQ2_XS a 2,1), encabezados
por un 35B, con el reclamo «90% less» y sin un solo aviso. Ordenaba por `-params_b` sin
mirar la cuantización, así que el ganador era siempre «el modelo más grande que quepa,
cueste lo que cueste».

Tres razones por las que eso estaba mal, y las tres son verificables:

1. **El repo ya lo había decidido.** `optimizer.most_powerful_per_compression` aplica desde
   siempre un piso `≥Q4_K_M` con el comentario «sin piso, el más potente sería siempre un
   modelo enorme a IQ1_S (1.5-bit, inservible)». Las dos vistas de la misma app decían
   cosas opuestas. Hay un test aquí que ata esa coherencia.
2. **La evidencia publicada apunta a 4 bits** (Dettmers & Zettlemoyer, ICML 2023: para un
   presupuesto fijo de bits totales, 4 bits es «casi universalmente óptimo»). Su barrido va
   de 3 a 8 bits: IQ1_S ni entra en el rango estudiado.
3. **inferbench no lo ha medido nunca**: cero runs a IQ1_S en la base de datos.

El piso decide qué se PRESENTA como recomendado, no qué se puede ejecutar:
`quality_floor=false` sigue devolviendo la lista sin piso.
"""

import pytest

from api.optimize import QUALITY_FLOOR, recommendations
from core import compat
from core.hardware import CPUInfo, GPUInfo, HardwareInfo
from core.optimizer import ENGINE_QUANTS, quants_above_floor

# 8 GB de VRAM: el caso que destapó el fallo. Con mucha VRAM el piso no se nota, porque
# los quants altos ya caben.
GPU_8GB = HardwareInfo(
    os="Windows",
    os_version="10",
    cpu=CPUInfo(name="test", arch="x86_64", physical_cores=8, logical_cores=16, freq_mhz=None),
    ram_gb=32.0,
    ram_available_gb=16.0,
    gpus=[GPUInfo(vendor="nvidia", name="RTX 3070", vram_gb=8.0, index=0)],
    primary_vram_gb=8.0,
)


@pytest.fixture
def hw_8gb(monkeypatch):
    """`detect_hardware` está cacheada con lru_cache; se parchea donde se USA."""
    import api.optimize as opt

    monkeypatch.setattr(opt, "detect_hardware", lambda: GPU_8GB)
    return GPU_8GB


async def test_ninguna_recomendacion_por_debajo_del_piso(hw_8gb):
    filas = await recommendations(top=15)

    assert filas, "sin recomendaciones no hay nada que juzgar"
    malas = [f for f in filas if (f.bits_per_weight or 0) < 4.0]
    assert not malas, "recomendadas por debajo de 4 bits/peso: " + ", ".join(
        f"{f.model.name} {f.config.quant} ({f.bits_per_weight})" for f in malas
    )


def test_el_piso_es_el_DEFECTO_por_HTTP(monkeypatch):
    """Llamar a la función en Python NO comprueba el defecto.

    Sin argumento, `quality_floor` vale el objeto `Query(True)` —que es truthy— así que el
    piso se aplicaba igual aunque el defecto fuese `Query(False)`. Un mutante que cambiaba
    el defecto sobrevivía a todos los tests de arriba. La única forma de comprobar el
    defecto de verdad es dejar que FastAPI lo resuelva: petición HTTP sin el parámetro.
    """
    from fastapi.testclient import TestClient

    import api.optimize as opt

    monkeypatch.setattr(opt, "detect_hardware", lambda: GPU_8GB)
    from main import app

    with TestClient(app) as cliente:
        r = cliente.get("/api/optimize/recommendations?top=15")
    assert r.status_code == 200
    filas = r.json()
    assert filas
    malas = [f for f in filas if (f.get("bits_per_weight") or 0) < 4.0]
    assert not malas, "sin pasar quality_floor, el defecto debe aplicar el piso: " + ", ".join(
        f"{f['model']['name']} {f['config']['quant']}" for f in malas
    )


async def test_sin_piso_se_puede_seguir_viendo(hw_8gb):
    """El piso no esconde nada: deja de PRESENTARLO como recomendación por defecto."""
    filas = await recommendations(top=15, quality_floor=False)

    assert any(
        (f.bits_per_weight or 99) < 3.0 for f in filas
    ), "con quality_floor=False deberían reaparecer los quants extremos"


async def test_el_piso_cambia_de_verdad_el_resultado(hw_8gb):
    """Si ambas listas coinciden, el parámetro es decorativo y el test de arriba no vale."""
    con = await recommendations(top=15)
    sin = await recommendations(top=15, quality_floor=False)

    assert [f.model.id for f in con] != [f.model.id for f in sin]


async def test_bits_por_peso_publicados_y_coherentes(hw_8gb):
    filas = await recommendations(top=15)

    for f in filas:
        assert f.bits_per_weight is not None, f"{f.model.name} sin bits/peso"
        assert f.bits_per_weight == compat.bits_per_weight(f.config.quant)


def test_el_piso_coincide_con_el_de_la_tabla_de_benchmark():
    """La contradicción original: dos vistas de la misma app con políticas distintas.

    `most_powerful_per_compression` fija su lista en `["Q8_0","Q6_K","Q5_K_M","Q4_K_M"]`.
    El piso del Dashboard tiene que terminar exactamente en el mismo sitio.
    """
    assert QUALITY_FLOOR["llamacpp"] == "Q4_K_M"
    assert quants_above_floor("llamacpp", "Q4_K_M") == ["Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M"]


def test_quants_above_floor_no_deja_al_usuario_sin_nada():
    """Un nombre de quant que no existe no puede vaciar la lista: mejor todo que nada."""
    assert quants_above_floor("llamacpp", "no-existe") == ENGINE_QUANTS["llamacpp"]
    assert quants_above_floor("llamacpp", None) == ENGINE_QUANTS["llamacpp"]


def test_bits_por_peso_de_la_tabla():
    assert compat.bits_per_weight("Q4_K_M") == 4.4
    assert compat.bits_per_weight("IQ1_S") == 1.5
    assert compat.bits_per_weight("Q8_0") == 8.0
    assert compat.bits_per_weight("inventado") is None
    # insensible a mayúsculas: el catálogo mezcla `q4_K_M` (ollama) y `Q4_K_M` (llama.cpp)
    assert compat.bits_per_weight("q4_K_M") == 4.4

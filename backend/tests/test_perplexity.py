"""El parseo se valida contra salidas REALES de llama-perplexity, no inventadas.

`backend/tests/fixtures/llama-perplexity-*.txt` son capturas literales de la herramienta
corriendo en esta máquina (llama.cpp, Llama-3.2-1B, corpus del repo). Si una versión futura
cambia una etiqueta, estos tests cantan antes de que el usuario vea un hueco en la tabla.

No hay ningún test aquí que ejecute el binario: cargar un modelo tarda y ocupa VRAM. Lo que
se prueba es todo lo que rodea a esa ejecución, que es donde están los fallos de verdad.
"""

from pathlib import Path

import pytest

from core import perplexity as ppl

FIXTURES = Path(__file__).parent / "fixtures"
SALIDA_KLD = (FIXTURES / "llama-perplexity-kld.txt").read_text(encoding="utf-8")
SALIDA_BASE = (FIXTURES / "llama-perplexity-base.txt").read_text(encoding="utf-8")


def test_parsea_la_comparacion_contra_la_referencia():
    m = ppl.parsear(SALIDA_KLD, "Q4_K_M")

    assert m.quant == "Q4_K_M"
    assert m.ppl == pytest.approx(1.874106)
    assert m.ppl_ratio == pytest.approx(1.010562)
    assert m.kld_media == pytest.approx(0.009224)
    assert m.kld_p99 == pytest.approx(0.089603)
    assert m.same_top_pct == pytest.approx(98.039)
    assert m.rms_dp_pct == pytest.approx(2.328)
    assert m.chunks == 2
    assert m.error is None


def test_parsea_la_referencia():
    m = ppl.parsear(SALIDA_BASE, "Q8_0", es_referencia=True)

    assert m.ppl == pytest.approx(24.6865)
    assert m.chunks == 3
    assert m.es_referencia
    # La referencia no se compara consigo misma: publicar un ratio de 1,0 haría creer
    # que está medido cuando no lo está.
    assert m.ppl_ratio is None
    assert m.kld_media is None
    assert m.same_top_pct is None


def test_la_referencia_no_publica_comparacion_ni_teniendola_delante():
    """La guarda de `es_referencia` hay que ejercerla con una salida que SÍ traiga los datos.

    Parsear la salida normal como referencia no prueba nada: esas líneas no existen ahí, así
    que sale None de todos modos y un fallo en la guarda pasaría desapercibido. Aquí se le
    da la salida COMPLETA de KLD y aun así no puede publicar comparación: compararse consigo
    misma daría un +0,00% que el usuario leería como «medido y sin daño».
    """
    m = ppl.parsear(SALIDA_KLD, "Q8_0", es_referencia=True)

    assert m.ppl is not None, "la perplejidad propia sí se publica"
    assert m.ppl_ratio is None
    assert m.kld_media is None
    assert m.kld_p99 is None
    assert m.same_top_pct is None
    assert m.rms_dp_pct is None


def test_una_salida_vacia_no_inventa_numeros():
    """Si la herramienta no dice nada, la medida va vacía. Cero sería una mentira."""
    m = ppl.parsear("", "Q4_K_M")

    assert m.ppl is None and m.kld_media is None and m.same_top_pct is None
    assert m.chunks == 0


def test_la_referencia_es_la_mejor_cuantizacion_disponible():
    assert ppl.elegir_referencia(["Q4_K_M", "Q8_0", "IQ2_XS"]) == "Q8_0"
    assert ppl.elegir_referencia(["IQ1_S", "Q2_K"]) == "Q2_K"
    assert ppl.elegir_referencia(["Q4_K_M", "F16"]) == "F16"
    assert ppl.elegir_referencia([]) is None


def test_un_quant_desconocido_no_puede_ganar_de_referencia():
    """Si algo raro se colara como el mejor, se compararía todo contra basura."""
    assert ppl.elegir_referencia(["Q4_K_M", "INVENTADO"]) == "Q4_K_M"
    assert ppl.rango_calidad("INVENTADO") > ppl.rango_calidad("IQ1_S")


@pytest.mark.parametrize(
    "nombre,esperado",
    [
        ("Llama-3.2-1B-Instruct-Q4_K_M.gguf", "Q4_K_M"),
        ("gemma-2-9b-it-IQ2_XS.gguf", "IQ2_XS"),
        ("Meta-Llama-3.1-8B-Instruct-Q8_0.gguf", "Q8_0"),
        ("modelo-F16.gguf", "F16"),
        ("sin-cuantizacion-en-el-nombre.gguf", "?"),
    ],
)
def test_saca_la_cuantizacion_del_nombre(nombre, esperado):
    assert ppl._quant_del_nombre(Path(nombre)) == esperado


def test_saca_el_modelo_del_nombre():
    assert (
        ppl._modelo_del_nombre(Path("Llama-3.2-1B-Instruct-Q4_K_M.gguf")) == "Llama-3.2-1B-Instruct"
    )
    assert ppl._modelo_del_nombre(Path("gemma-2-9b-it-IQ2_XS.gguf")) == "gemma-2-9b-it"


def test_el_corpus_por_defecto_existe_y_es_prosa_de_verdad():
    """La perplejidad depende del texto: sobre el haystack sintético da 1,86 y aplana
    las diferencias entre cuantizaciones. Este corpus tiene que seguir siendo prosa."""
    c = ppl.corpus_por_defecto()

    assert c.is_file(), "falta backend/data/quality_corpus.txt"
    texto = c.read_text(encoding="utf-8")
    assert len(texto) > 100_000, "un corpus corto da medidas con demasiado error"
    # Bilingüe a propósito: la app es ES/EN y una cuantización puede dañar más un idioma.
    assert "Quijote" in texto and "Bennet" in texto
    # Sin la cabecera de Project Gutenberg (el texto es dominio público; la cabecera no).
    assert "PROJECT GUTENBERG" not in texto[:3000].upper()


async def test_la_comparativa_mide_la_referencia_primero_y_no_la_repite(monkeypatch, tmp_path):
    """El orden importa: sin logits de referencia no hay contra qué comparar."""
    llamadas: list[tuple[str, str]] = []

    async def falsa_ref(modelo, **kw):
        llamadas.append(("ref", ppl._quant_del_nombre(modelo)))
        kw.get("al_avanzar", lambda n: None)(1)
        return tmp_path / "base.dat", ppl.parsear(SALIDA_BASE, "Q8_0", es_referencia=True)

    async def falsa_contra(modelo, base, **kw):
        llamadas.append(("contra", ppl._quant_del_nombre(modelo)))
        return ppl.parsear(SALIDA_KLD, ppl._quant_del_nombre(modelo))

    monkeypatch.setattr(ppl, "medir_referencia", falsa_ref)
    monkeypatch.setattr(ppl, "medir_contra", falsa_contra)

    modelos = {
        "Q4_K_M": Path("m-Q4_K_M.gguf"),
        "Q8_0": Path("m-Q8_0.gguf"),
        "IQ2_XS": Path("m-IQ2_XS.gguf"),
    }
    eventos: list[dict] = []
    comp = await ppl.comparar_quants(modelos, al_evento=eventos.append)

    assert comp.referencia == "Q8_0"
    assert llamadas[0] == ("ref", "Q8_0")
    assert ("contra", "Q8_0") not in llamadas, "la referencia no se compara consigo misma"
    assert {q for tipo, q in llamadas if tipo == "contra"} == {"Q4_K_M", "IQ2_XS"}
    assert len(comp.medidas) == 3
    assert [e["type"] for e in eventos][0] == "start"
    assert [e["type"] for e in eventos][-1] == "done"


async def test_si_la_referencia_falla_se_para(monkeypatch, tmp_path):
    """Devolver medidas sin referencia sería enseñar números incomparables como si lo fueran."""

    async def ref_rota(modelo, **kw):
        m = ppl.MedidaCuant(quant="Q8_0", es_referencia=True, error="failed to load model")
        return tmp_path / "base.dat", m

    async def no_debe_llamarse(*a, **k):
        raise AssertionError("no se puede comparar sin referencia")

    monkeypatch.setattr(ppl, "medir_referencia", ref_rota)
    monkeypatch.setattr(ppl, "medir_contra", no_debe_llamarse)

    eventos: list[dict] = []
    comp = await ppl.comparar_quants(
        {"Q8_0": Path("m-Q8_0.gguf"), "Q4_K_M": Path("m-Q4_K_M.gguf")},
        al_evento=eventos.append,
    )

    assert len(comp.medidas) == 1
    assert any(e["type"] == "error" for e in eventos)


async def test_sin_modelos_no_revienta():
    comp = await ppl.comparar_quants({})

    assert comp.medidas == [] and comp.referencia is None


def test_el_error_dice_el_motivo_real():
    salida = "load_model: some info\nerror loading model: unable to allocate CUDA memory\n"
    assert "unable to allocate" in ppl._ultimo_error(salida)
    assert ppl._ultimo_error("") == "llama-perplexity falló sin mensaje"

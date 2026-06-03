"""Tests de los scorers de calidad (heurístico, checklist, ejecución de código) y el
parseo del LLM-judge (core/benchmark.py)."""
import asyncio

from core.benchmark import (
    _parse_judge_score,
    _quality_code,
    _quality_heuristic,
    _quality_keywords,
    load_prompts,
)

_REF_NUM = "Bea paga 250€, Ana 500€, Carlos 750€. Total 1500€."


def test_empty_output_is_zero():
    assert _quality_heuristic("", _REF_NUM) == 0.0


def test_correct_numeric_answer_scores_high():
    out = "Bea paga 250€, Ana el doble 500€, Carlos el triple 750€. Suma 250+500+750=1500€."
    assert _quality_heuristic(out, _REF_NUM) >= 70


def test_offtopic_answer_scores_low():
    out = "Las plantas necesitan agua y sol para crecer mediante la fotosíntesis."
    assert _quality_heuristic(out, _REF_NUM) < 25


def test_correct_beats_wrong():
    good = "Bea 250, Ana 500, Carlos 750, total 1500."
    bad = "Cada uno paga 500 dividiendo entre tres."
    assert _quality_heuristic(good, _REF_NUM) > _quality_heuristic(bad, _REF_NUM)


def test_degenerate_repetition_penalized():
    rep = ("no se " * 30).strip()
    assert _quality_heuristic(rep, _REF_NUM) < 20


def test_no_reference_capped_at_70():
    out = "Te recomiendo tres libros de ciencia ficción modernos muy entretenidos. " * 5
    score = _quality_heuristic(out, "")
    assert 0 < score <= 70


def test_stemming_matches_inflections():
    # "energético"/"regulación" deben casar con "energía"/"regula" del ref vía stem
    ref = "retos de energía y regulación de la inteligencia"
    out = "hay retos de consumo energético y de regulación sobre la inteligencia artificial"
    assert _quality_heuristic(out, ref) >= 50


_GOOD_CODE = """```python
def merge_intervals(intervals):
    iv = sorted(intervals)
    out = []
    for s, e in iv:
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out
```"""

_CODE_TESTS = [
    "assert [tuple(i) for i in merge_intervals([(1,3),(2,6),(8,10)])] == [(1,6),(8,10)]",
    "assert list(merge_intervals([])) == []",
]


def test_code_scorer_all_pass_is_100():
    # El código del modelo se EJECUTA contra casos reales; si pasan todos → 100.
    assert asyncio.run(_quality_code(_GOOD_CODE, _CODE_TESTS)) == 100.0


def test_code_scorer_partial():
    half = "```python\ndef merge_intervals(x):\n    return x  # no fusiona\n```"
    score = asyncio.run(_quality_code(half, _CODE_TESTS))
    assert 0 < score < 100  # pasa el caso vacío, falla el de fusión


def test_code_scorer_no_code_or_wrong_name_is_zero():
    assert asyncio.run(_quality_code("no hay bloque de código aquí", _CODE_TESTS)) == 0.0
    bad = "```python\ndef otra(x):\n    return x\n```"
    assert asyncio.run(_quality_code(bad, _CODE_TESTS)) == 0.0


def test_keywords_number_boundary_no_false_positive():
    # "500" NO debe casar dentro de "1500" (el total) → nada de aciertos inventados.
    groups = [["250"], ["500"], ["750"]]
    assert _quality_keywords("El alquiler total es 1500€ para los tres.", groups) == 0.0
    assert _quality_keywords("Bea 250, Ana 500, Carlos 750, total 1500.", groups) == 100.0


def test_long_context_prompt_loads_haystack():
    # El prompt de contexto largo antepone un documento de ~5k tokens con el needle.
    from core.benchmark import _prompt_user_text, get_prompt

    p = get_prompt("long-context")
    assert p is not None and p.context_file
    text = _prompt_user_text(p)
    assert len(text) > 5000  # el haystack se antepuso (estresa la ventana de contexto)
    assert "AZUL-4729" in text  # el dato escondido está en el contexto
    assert text.rstrip().endswith(p.prompt)  # la pregunta va al final


def test_every_prompt_has_a_verifiable_scorer():
    # Política: ningún prompt se evalúa por F1 de tokens a secas — todos llevan checklist
    # (keywords) o ejecución de código (code_tests).
    for p in load_prompts():
        assert p.keywords or p.code_tests, f"{p.id} no tiene scorer verificable"


def test_parse_judge_score():
    assert _parse_judge_score("85") == 85.0
    assert _parse_judge_score("I rate it 92 out of 100") == 92.0  # primer entero en rango
    assert _parse_judge_score("0") == 0.0
    assert _parse_judge_score("200 then 75") == 75.0  # 200 fuera de rango, salta a 75
    assert _parse_judge_score("Score: 100") == 100.0
    assert _parse_judge_score("no number here") is None
    assert _parse_judge_score("") is None

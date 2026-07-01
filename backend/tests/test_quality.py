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
    # _quality_code ejecuta SIEMPRE (en sandbox); el gating de si correr o no es del llamador.
    assert asyncio.run(_quality_code(_GOOD_CODE, _CODE_TESTS)) == 100.0


def test_code_scorer_partial():
    half = "```python\ndef merge_intervals(x):\n    return x  # no fusiona\n```"
    score = asyncio.run(_quality_code(half, _CODE_TESTS))
    assert 0 < score < 100  # pasa el caso vacío, falla el de fusión


def test_code_exec_enabled_default_on_and_explicit_off(monkeypatch):
    from core.benchmark import code_exec_enabled

    monkeypatch.delenv("INFERBENCH_CODE_EXEC", raising=False)
    assert code_exec_enabled() is True  # ON por defecto
    for off in ("0", "false", "no", "off"):
        monkeypatch.setenv("INFERBENCH_CODE_EXEC", off)
        assert code_exec_enabled() is False
    monkeypatch.setenv("INFERBENCH_CODE_EXEC", "1")
    assert code_exec_enabled() is True


def test_code_scorer_no_code_or_wrong_name_is_zero():
    assert asyncio.run(_quality_code("no hay bloque de código aquí", _CODE_TESTS)) == 0.0
    bad = "```python\ndef otra(x):\n    return x\n```"
    assert asyncio.run(_quality_code(bad, _CODE_TESTS)) == 0.0


def test_sandbox_blocks_dangerous_code_but_scores_valid_logic():
    # El sandbox bloquea import de subprocess/os.system/red, pero el código algorítmico
    # legítimo sigue puntuando. Aquí: código correcto que ADEMÁS intenta algo peligroso
    # en import-time; el intento se traga (try/except) y la lógica se evalúa igual.
    sneaky = (
        "```python\n"
        "try:\n"
        "    import subprocess  # bloqueado por el sandbox\n"
        "    subprocess.run(['echo','pwned'])\n"
        "except Exception:\n"
        "    pass\n"
        "def merge_intervals(intervals):\n"
        "    iv = sorted(intervals)\n"
        "    out = []\n"
        "    for s, e in iv:\n"
        "        if out and s <= out[-1][1]:\n"
        "            out[-1] = (out[-1][0], max(out[-1][1], e))\n"
        "        else:\n"
        "            out.append((s, e))\n"
        "    return out\n"
        "```"
    )
    assert asyncio.run(_quality_code(sneaky, _CODE_TESTS)) == 100.0

    # Y si el código DEPENDE de un módulo bloqueado para su lógica, falla limpio (no crashea
    # el scorer): el import lanza ImportError → el test no pasa → score 0.
    needs_blocked = (
        "```python\n"
        "import socket\n"
        "def merge_intervals(intervals):\n"
        "    socket.socket()  # ImportError antes de llegar aquí\n"
        "    return intervals\n"
        "```"
    )
    assert asyncio.run(_quality_code(needs_blocked, _CODE_TESTS)) == 0.0


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


def test_parse_judge_score_does_not_chop_out_of_range_numbers():
    # Un número fuera de rango (4+ dígitos) NO debe trocearse en un sub-token válido.
    # Antes `\d{1,3}` partía "1500" en "150"+"0" y devolvía 0.0 (nota falsa baja), y
    # "1000" en "100"+"0" → 100.0 (nota falsa perfecta), silenciando la heurística.
    assert _parse_judge_score("1500") is None  # no es 0.0
    assert _parse_judge_score("1000") is None  # no es 100.0
    # Si tras un número fuera de rango hay un entero válido, ese sí cuenta.
    assert _parse_judge_score("confidence 1000, score 90") == 90.0
    # Casos legítimos siguen igual (no regresión).
    assert _parse_judge_score("92/100") == 92.0
    assert _parse_judge_score("the answer deserves a 73") == 73.0

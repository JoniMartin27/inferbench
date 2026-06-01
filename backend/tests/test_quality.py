"""Tests del scorer de calidad offline y el parseo del LLM-judge (core/benchmark.py)."""
from core.benchmark import _parse_judge_score, _quality_heuristic

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


def test_parse_judge_score():
    assert _parse_judge_score("85") == 85.0
    assert _parse_judge_score("I rate it 92 out of 100") == 92.0  # primer entero en rango
    assert _parse_judge_score("0") == 0.0
    assert _parse_judge_score("200 then 75") == 75.0  # 200 fuera de rango, salta a 75
    assert _parse_judge_score("Score: 100") == 100.0
    assert _parse_judge_score("no number here") is None
    assert _parse_judge_score("") is None

"""Comprobaciones ponderadas (`Check`) y validación de la batería de prompts.

Dos bloques:
  1. El motor de comprobaciones: que cada tipo mida lo que dice medir y, sobre todo, que
     RECHACE lo que el checklist de keywords dejaba pasar (números como prefijo, asignaciones
     cruzadas, listas desordenadas, alucinaciones añadidas).
  2. El contrato de la batería: todo prompt tiene scorer verificable, dificultad y versión;
     todos los patrones compilan; y —lo que de verdad valida un baremo— una respuesta MODELO
     saca 100 y una mala se queda claramente por debajo. Un baremo que nadie puede aprobar
     está tan roto como uno que aprueba cualquier cosa.
"""

from __future__ import annotations

import re

import pytest
from core.benchmark import (
    Check,
    _check_passes,
    _failed_checks,
    _num_spans,
    _q_norm,
    _quality_checks,
    get_prompt,
    load_prompts,
)


def score(output: str, *checks: Check) -> float:
    return _quality_checks(output, list(checks))


# --------------------------- 1. el motor de comprobaciones ---------------------------


def test_any_matches_synonyms_and_morphology():
    c = Check(kind="any", of=["circle", "circulo"])
    assert _check_passes(c, _q_norm("Hay un círculo rojo"))
    assert _check_passes(c, _q_norm("two circles"))  # prefijo: circle → circles
    assert not _check_passes(c, _q_norm("a red square"))


def test_number_does_not_match_as_a_prefix_or_a_suffix():
    # El fallo MEDIDO del checklist viejo: "250" contaba dentro de "2500".
    assert _num_spans("ana paga 2500", "250") == []
    assert _num_spans("el total es 1250", "250") == []
    assert _num_spans("total 5000", "500") == []
    assert _num_spans("ana paga 250 euros", "250") != []
    assert _num_spans("son 250€ al mes", "250") != []
    assert _num_spans("(250)", "250") != []


def test_number_accepts_thousand_separators():
    assert _num_spans("el alquiler es 2.450 euros", "2450") != []
    assert _num_spans("el alquiler es 2,450 euros", "2450") != []


def test_number_near_verifies_the_assignment_not_just_proximity():
    ok = Check(kind="number", value="800", near=["carlos"])
    # Asignación correcta.
    assert _check_passes(ok, _q_norm("Result: Ana=400, Bea=600, Carlos=800, Dana=650"))
    assert _check_passes(ok, _q_norm("Carlos pays 800 euros a month"))
    # Asignación CRUZADA: en una línea compacta "carlos" está a 19 caracteres del 800, así
    # que una regla de mera cercanía la daría por buena. Hay dígitos por medio → no cuela.
    assert not _check_passes(ok, _q_norm("Result: Ana=800, Bea=600, Carlos=400, Dana=650"))


def test_number_near_works_in_both_directions():
    c = Check(kind="number", value="400", near=["ana"])
    assert _check_passes(c, _q_norm("Ana pays 400"))
    assert _check_passes(c, _q_norm("400 euros correspond to Ana"))
    assert not _check_passes(c, _q_norm("Bea pays 600 and Ana pays 900"))


def test_number_near_respects_the_window():
    c = Check(kind="number", value="400", near=["ana"], window=10)
    assert _check_passes(c, _q_norm("ana: 400"))
    lejos = "ana" + " palabra sin cifras" * 5 + " 400"
    assert not _check_passes(c, _q_norm(lejos))


def test_order_requires_the_requested_sequence():
    c = Check(
        kind="order",
        of=[["mercury"], ["venus"], ["earth", "tierra"]],
        label="orden",
    )
    assert _check_passes(c, _q_norm("Mercury, Venus, Earth"))
    assert not _check_passes(c, _q_norm("Venus, Mercury, Earth"))  # desordenado
    assert not _check_passes(c, _q_norm("Mercury and Venus"))  # falta uno


def test_absent_catches_added_facts_and_numeric_decoys():
    c = Check(kind="absent", of=["pluto", "612"])
    assert _check_passes(c, _q_norm("Mercury, Venus, Earth"))
    assert not _check_passes(c, _q_norm("... and Pluto"))
    assert not _check_passes(c, _q_norm("each one pays 612 euros"))
    # El señuelo numérico se compara como número completo: 6125 no es 612.
    assert _check_passes(c, _q_norm("el codigo es 6125"))


def test_absent_supports_a_pattern():
    c = Check(kind="absent", pattern=r"\d{1,3}\s*%")
    assert _check_passes(c, _q_norm("El texto habla de privacidad y sesgo."))
    assert not _check_passes(c, _q_norm("El 40% de las empresas lo usa."))


def test_regex_anchors_at_line_start():
    c = Check(kind="regex", pattern=r"^\s*1\s*[:.)\-]\s*canberra\b")
    assert _check_passes(c, _q_norm("1: Canberra\n2: Ankara"))
    assert _check_passes(c, _q_norm("Sure!\n1. Canberra"))
    # Decirlo suelto en prosa NO cumple el formato pedido.
    assert not _check_passes(c, _q_norm("The capital of Australia is Canberra."))


def test_weights_give_partial_credit():
    a = Check(kind="any", of=["alpha"], weight=3)
    b = Check(kind="any", of=["beta"], weight=1)
    assert score("alpha", a, b) == 75.0
    assert score("beta", a, b) == 25.0
    assert score("alpha beta", a, b) == 100.0
    assert score("nada", a, b) == 0.0


def test_empty_or_broken_checks_do_not_crash_and_score_zero():
    assert _quality_checks("lo que sea", []) == 0.0
    assert score("x", Check(kind="inventado", of=["x"])) == 0.0
    assert score("x", Check(kind="regex", pattern="([unclosed")) == 0.0
    assert score("x", Check(kind="number")) == 0.0
    assert score("x", Check(kind="order")) == 0.0


def test_silence_earns_nothing_even_if_every_absent_check_holds():
    # Las comprobaciones `absent` se cumplen solas cuando no se dice nada. Sin esta regla,
    # una respuesta VACÍA sacaba 62,5 en el prompt de no-alucinar (fallo real, cazado por
    # `test_an_empty_or_offtopic_answer_scores_low_everywhere`).
    checks = [
        Check(kind="any", of=["not stated"], weight=3, label="dice que no consta"),
        Check(kind="absent", of=["320"], weight=3, label="no inventa la cifra"),
    ]
    assert _quality_checks("", checks) == 0.0
    assert _quality_checks("ni idea, lo siento", checks) == 0.0
    assert _quality_checks("that is not stated in the passage", checks) == 100.0


def test_failed_checks_explains_the_score():
    checks = [
        Check(kind="any", of=["alpha"], label="dice alpha"),
        Check(kind="any", of=["beta"], label="dice beta"),
    ]
    assert _failed_checks("solo alpha", checks) == ["dice beta"]
    assert _failed_checks("alpha y beta", checks) == []


# --------------------------- 2. contrato de la batería ---------------------------

_KINDS = {"any", "number", "order", "regex", "absent"}


def test_every_prompt_declares_difficulty_and_version():
    for p in load_prompts():
        assert p.difficulty in ("easy", "medium", "hard"), p.id
        assert p.version >= 1, p.id


def test_the_suite_covers_the_three_difficulty_tiers():
    # Una batería de un solo tramo no ordena modelos: los pequeños sacan 0 en todo o los
    # grandes sacan 100 en todo. MEDIDO en la batería anterior: 3 de 7 prompts saturados.
    tramos = {p.difficulty for p in load_prompts()}
    assert tramos == {"easy", "medium", "hard"}
    duros = [p.id for p in load_prompts() if p.difficulty == "hard"]
    assert len(duros) >= 4, f"pocos prompts duros: {duros}"


def test_every_prompt_has_a_verifiable_scorer():
    # Política: ningún prompt se evalúa por F1 de tokens a secas.
    for p in load_prompts():
        assert p.checks or p.keywords or p.code_tests, f"{p.id} no tiene scorer verificable"


def test_all_checks_are_well_formed():
    for p in load_prompts():
        for c in p.checks or []:
            assert c.kind in _KINDS, f"{p.id}: tipo desconocido {c.kind}"
            assert c.label, f"{p.id}: comprobación sin etiqueta ({c.kind})"
            assert c.weight > 0, f"{p.id}: peso no positivo en {c.label}"
            if c.kind == "number":
                assert c.value, f"{p.id}: `number` sin valor en {c.label}"
            if c.kind == "order":
                assert c.of and len(c.of) >= 2, f"{p.id}: `order` necesita ≥2 grupos"
            if c.kind in ("any", "absent") and c.of:
                assert all(isinstance(t, str) for t in c.of), f"{p.id}: {c.label}"
            if c.pattern:
                re.compile(c.pattern)  # revienta el test si no compila
            if c.kind == "absent":
                assert c.of or c.pattern, f"{p.id}: `absent` sin términos ni patrón"


def test_every_prompt_has_at_least_one_positive_check():
    # Un prompt hecho solo de `absent` premiaría el silencio (ver `_quality_checks`).
    for p in load_prompts():
        if not p.checks:
            continue
        assert any(c.kind != "absent" for c in p.checks), f"{p.id}: solo comprobaciones `absent`"


def test_check_labels_are_english_like_the_rest_of_the_ui():
    # El backend es english-first (contrato de i18n): las etiquetas salen por SSE a la UI.
    acentos = re.compile(r"[áéíóúñ¿¡]", re.IGNORECASE)
    for p in load_prompts():
        for c in p.checks or []:
            assert not acentos.search(c.label), f"{p.id}: etiqueta en castellano: {c.label}"


# Respuestas MODELO: lo que debería contestar un modelo perfecto. Si una de estas no saca
# 100, el baremo es imposible de aprobar (y el prompt no mide, solo castiga).
RESPUESTAS_PERFECTAS = {
    "chat": "Mercury, Venus, Earth, Mars, Jupiter, Saturn, Uranus, Neptune",
    "reasoning": (
        "Let a be what Ana pays. Bea pays a+200, Carlos 2a, Dana 2a-150.\n"
        "a + (a+200) + 2a + (2a-150) = 6a + 50 = 2450, so a = 400.\n"
        "Check: 400 + 600 + 800 + 650 = 2450.\n"
        "Result: Ana=400, Bea=600, Carlos=800, Dana=650"
    ),
    "logic": (
        "Farid is right after Dana, so (Dana, Farid) is 3rd and 4th; Gus is before Elena "
        "and Elena is not last, so Gus is 1st and Elena 2nd.\n"
        "1: Gus\n2: Elena\n3: Dana\n4: Farid"
    ),
    "instructions": "1: Canberra\n2: Ankara\n3: Ottawa",
    "json-extract": '{"invoice": "88-B", "client": "Nordwind GmbH", "total": 61.00}',
    "summary": (
        "1. Generative AI has transformed the software industry.\n"
        "2. Large language models write code and translate between languages.\n"
        "3. They also draft documents and reason about complex problems.\n"
        "4. They raise concerns about privacy, bias and energy use in data centers.\n"
        "5. Companies and governments work on regulation and ethical frameworks."
    ),
    "unanswerable": (
        "The passage does not say anything about a Valencia plant; it only mentions the "
        "Almeria one, so the number of employees is not stated."
    ),
    "long-context": "AZUL-4729",
    "long-context-count": "7",
    "vision-scene": (
        "There are three shapes: a red circle at the top left, a blue square at the top "
        "right and a green triangle at the bottom."
    ),
    "vision-count": "There are four orange circles.",
}

# Respuestas MALAS plausibles: el fallo típico que el prompt tiene que castigar.
RESPUESTAS_MALAS = {
    "chat": "Venus, Mercury, Mars, Earth, Jupiter, Saturn, Neptune, Uranus and Pluto",
    "reasoning": "Each of the four flatmates pays the same: 612.5 euros.",
    "logic": "1: Dana\n2: Farid\n3: Gus\n4: Elena",
    "instructions": "Of course! The capital of Australia is Sydney, Turkey's is Istanbul.",
    "json-extract": '```json\n{"invoice": "88-B", "client": "Nordwind GmbH", "total": 52.00}\n```',
    "unanswerable": "The Valencia plant employs 320 people.",
    "long-context": "The access code is BRONCE-1188.",
    "long-context-count": "There are 120 records in the document.",
    "vision-scene": "I see a yellow hexagon and a purple star.",
    "vision-count": "There are two orange squares.",
}


@pytest.mark.parametrize("pid", sorted(RESPUESTAS_PERFECTAS))
def test_a_perfect_answer_scores_100(pid):
    p = get_prompt(pid)
    assert p is not None and p.checks, f"{pid} no usa comprobaciones"
    nota = _quality_checks(RESPUESTAS_PERFECTAS[pid], p.checks)
    assert (
        nota == 100.0
    ), f"{pid}: {nota} — falla {_failed_checks(RESPUESTAS_PERFECTAS[pid], p.checks)}"


@pytest.mark.parametrize("pid", sorted(RESPUESTAS_MALAS))
def test_a_typical_wrong_answer_is_clearly_penalised(pid):
    p = get_prompt(pid)
    assert p is not None and p.checks
    nota = _quality_checks(RESPUESTAS_MALAS[pid], p.checks)
    assert nota <= 60.0, f"{pid}: una respuesta mala saca {nota}"


def test_an_empty_or_offtopic_answer_scores_low_everywhere():
    for p in load_prompts():
        if not p.checks:
            continue
        assert _quality_checks("", p.checks) <= 40.0, p.id
        assert _quality_checks("I am not sure about that, sorry.", p.checks) <= 60.0, p.id

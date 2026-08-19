"""La auditoría de la batería (`scripts/audit_scoring.py`) sobre una BD desechable.

Lo que se ata aquí es lo que hace útil a la herramienta: que NO mezcle versiones distintas
del mismo prompt. Re-puntuar una respuesta vieja con el baremo nuevo da un número que parece
información y no lo es — la respuesta contestaba a otra pregunta.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest
from core.benchmark import get_prompt

RUTA = Path(__file__).resolve().parent.parent / "scripts" / "audit_scoring.py"


def _cargar_script():
    spec = importlib.util.spec_from_file_location("audit_scoring", RUTA)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["audit_scoring"] = mod
    spec.loader.exec_module(mod)
    return mod


ESQUEMA = """
CREATE TABLE benchmark_results (
    id INTEGER PRIMARY KEY, run_id TEXT, model_id TEXT, prompt_id TEXT,
    tps FLOAT, ttft_ms INTEGER, vram_gb FLOAT, ram_gb FLOAT, quality FLOAT,
    cost FLOAT, ctx_used INTEGER, raw_output TEXT, error TEXT,
    prompt_version INTEGER, scorer TEXT
)
"""

PERFECTA = "Mercury, Venus, Earth, Mars, Jupiter, Saturn, Uranus, Neptune"
DE_OTRA_PREGUNTA = "Te recomiendo tres libros de ciencia ficcion modernos: ..."


def _bd(tmp_path: Path, filas) -> str:
    ruta = tmp_path / "audit.sqlite"
    con = sqlite3.connect(ruta)
    con.execute(ESQUEMA)
    con.executemany(
        "INSERT INTO benchmark_results (run_id, model_id, prompt_id, raw_output, error,"
        " prompt_version, quality) VALUES (?,?,?,?,?,?,?)",
        filas,
    )
    con.commit()
    con.close()
    return str(ruta)


def _correr(mod, db: str, *extra) -> str:
    from io import StringIO

    viejo, sys.argv = sys.argv, ["audit_scoring.py", "--db", db, *extra]
    salida, sys.stdout = sys.stdout, StringIO()
    try:
        mod.main()
        return sys.stdout.getvalue()
    finally:
        sys.stdout, sys.argv = salida, viejo


@pytest.fixture(scope="module")
def mod():
    return _cargar_script()


def test_discards_rows_from_another_prompt_version(mod, tmp_path):
    v = get_prompt("chat").version
    filas = [
        ("r1", "m", "chat", DE_OTRA_PREGUNTA, "", v - 1, 55.0),  # otra versión: fuera
        ("r1", "m", "chat", PERFECTA, "", v, 100.0),  # vigente: cuenta
        ("r1", "m", "chat", PERFECTA, "", None, 100.0),  # sin versión: fuera
    ]
    out = _correr(mod, _bd(tmp_path, filas))
    assert "2 filas descartadas" in out
    # La única fila vigente es perfecta → una sola nota, 100.
    linea = [ln for ln in out.splitlines() if ln.startswith("chat")]
    assert len(linea) == 1 and "100.0" in linea[0]


def test_rows_with_errors_or_no_output_are_not_scored(mod, tmp_path):
    v = get_prompt("chat").version
    filas = [
        ("r1", "m", "chat", "", "boom", v, 0.0),
        ("r1", "m", "chat", "   ", "", v, 0.0),
    ]
    out = _correr(mod, _bd(tmp_path, filas))
    assert "Todavía no hay resultados de la batería vigente" in out


def test_reports_which_checks_fail(mod, tmp_path):
    v = get_prompt("chat").version
    desordenado = "Venus, Mercury, Earth, Mars, Jupiter, Saturn, Neptune, Uranus"
    out = _correr(mod, _bd(tmp_path, [("r1", "m", "chat", desordenado, "", v, 0.0)]), "--compare")
    assert "in order from the Sun" in out


def test_never_writes_to_the_database(mod, tmp_path):
    # El script audita el HISTORIAL DEL USUARIO. Aquí ya se destruyó una vez con un test
    # (135 filas marcadas `interrupted`): esto se comprueba byte a byte, no leyendo el
    # código. Se ejecuta la auditoría entera y la BD tiene que quedar idéntica.
    import hashlib

    v = get_prompt("chat").version
    db = _bd(tmp_path, [("r1", "m", "chat", PERFECTA, "", v, 100.0)])
    antes = hashlib.md5(Path(db).read_bytes()).hexdigest()
    _correr(mod, db, "--compare")
    assert hashlib.md5(Path(db).read_bytes()).hexdigest() == antes
    # Y además, que la conexión sea explícitamente de solo lectura.
    fuente = RUTA.read_text(encoding="utf-8")
    assert "mode=ro" in fuente
    for verbo in ("INSERT INTO", "UPDATE ", "DELETE FROM", "DROP ", "ALTER "):
        assert verbo not in fuente.upper(), verbo

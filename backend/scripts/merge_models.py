"""Aplica correcciones, rellena n_layer, valida contra el schema y fusiona en models.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.models_catalog import Model  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "data" / "models.json"

# Correcciones de repo/template para matches que la búsqueda eligió mal
REPO_FIX = {
    "llama-3-8b": ("bartowski/Meta-Llama-3-8B-Instruct-GGUF", "Meta-Llama-3-8B-Instruct-{quant}.gguf"),
    "ministral-8b": ("bartowski/Ministral-8B-Instruct-2410-HF-GGUF", "Ministral-8B-Instruct-2410-HF-{quant}.gguf"),
    "glm-4-9b": ("bartowski/glm-4-9b-chat-GGUF", "glm-4-9b-chat-{quant}.gguf"),
}

# n_layer por arquitectura (para los que el config.json estaba gated → None)
NLAYER_FIX = {
    "gemma-3-1b": 26, "gemma-3-4b": 34, "gemma-3-12b": 48, "gemma-3-27b": 62,
    "mistral-small-3.1-24b": 40, "llama-3-8b": 32,
    "exaone-3.5-7.8b": 32, "exaone-3.5-2.4b": 30,
    "aya-expanse-8b": 32, "aya-expanse-32b": 40, "command-r7b": 32,
}

new = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
existing = json.loads(MODELS.read_text(encoding="utf-8"))
existing_ids = {m["id"] for m in existing}

added, skipped, errors = [], [], []
for m in new:
    if m["id"] in existing_ids:
        skipped.append(m["id"])
        continue
    if m["id"] in REPO_FIX:
        repo, tmpl = REPO_FIX[m["id"]]
        m["hf_gguf"] = {"repo": repo, "file_template": tmpl}
    if not m.get("n_layer") and m["id"] in NLAYER_FIX:
        m["n_layer"] = NLAYER_FIX[m["id"]]
    # tamaño base coherente con params si no se fijó
    m["size_base_gb"] = round(m["params_b"] * 2, 1)
    try:
        Model.model_validate(m)
    except Exception as e:
        errors.append((m["id"], str(e)))
        continue
    added.append(m)

if errors:
    for i, why in errors:
        print(f"VALIDATION FAIL {i}: {why}", file=sys.stderr)
    sys.exit(1)

# Avisar de los que quedaron sin n_layer (no es fatal, pero conviene saberlo)
no_layer = [m["id"] for m in added if not m.get("n_layer")]
if no_layer:
    print(f"WARN sin n_layer: {no_layer}", file=sys.stderr)

merged = existing + added
MODELS.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Añadidos: {len(added)} | Saltados (ya existían): {skipped} | Total catálogo: {len(merged)}", file=sys.stderr)
print(f"Nuevos ids: {[m['id'] for m in added]}", file=sys.stderr)

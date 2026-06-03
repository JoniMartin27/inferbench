"""Verifica candidatos de modelos contra HuggingFace y deriva file_template real.

Uso: python scripts/verify_models.py
No inventa datos: solo emite modelos cuyo repo GGUF y archivo Q4_K_M existen de verdad.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
import urllib.error

HF = "https://huggingface.co"
QUANT_TOKENS = ["Q4_K_M", "Q4_K_S", "Q5_K_M", "Q6_K", "Q8_0", "Q3_K_M", "Q3_K_L", "Q2_K", "IQ4_XS", "IQ4_NL"]
PREFERRED_AUTHORS = ["bartowski", "lmstudio-community", "unsloth", "ggml-org"]


def _get_json(url: str, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "inferbench-verify"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"__error__": str(e)}


def _head_ok(url: str, timeout=12) -> bool:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "inferbench-verify"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status not in (401, 403, 404)
    except urllib.error.HTTPError as e:
        return e.code not in (401, 403, 404)
    except Exception:
        return False  # conservador: si falla, no lo damos por bueno


def find_gguf_repo(search: str, official_author: str | None) -> str | None:
    """Busca el mejor repo *-GGUF para un término."""
    authors = list(PREFERRED_AUTHORS)
    if official_author:
        authors.append(official_author)
    data = _get_json(f"{HF}/api/models?search={urllib.parse.quote(search)}&limit=40")
    if isinstance(data, dict) and data.get("__error__"):
        return None
    cands = [m["id"] for m in data if m.get("id", "").endswith("-GGUF") or "GGUF" in m.get("id", "")]
    # priorizar por autor preferido
    for a in authors:
        for cid in cands:
            if cid.lower().startswith(a.lower() + "/"):
                return cid
    return cands[0] if cands else None


def derive_template(repo: str) -> tuple[str | None, str | None, bool]:
    """Devuelve (file_template, quant_de_prueba, multipart) a partir de los .gguf del repo.

    Prioriza single-file; si no hay, detecta GGUF partido en shards (modelos enormes) y
    devuelve la plantilla lógica + multipart=True (la descarga junta todos los shards).
    """
    data = _get_json(f"{HF}/api/models/{repo}")
    if isinstance(data, dict) and data.get("__error__"):
        return None, None, False
    sib = [s.get("rfilename", "") for s in data.get("siblings", [])]
    ggufs = [f for f in sib if f.endswith(".gguf") and "/" not in f]
    for tok in QUANT_TOKENS:
        for f in ggufs:
            if tok in f and "of-0" not in f:
                return f.replace(tok, "{quant}"), tok, False
    # Sin single-file: buscar shards (suelen vivir en un subdir por quant)
    shards = [f for f in sib if re.search(r"-\d{5}-of-\d{5}\.gguf$", f)]
    for tok in QUANT_TOKENS:
        for f in shards:
            m = re.search(rf"([^/]+)-{re.escape(tok)}-\d{{5}}-of-\d{{5}}\.gguf$", f)
            if m:
                return f"{m.group(1)}-{{quant}}.gguf", tok, True
    return None, None, False


def fetch_config(repo: str | None) -> dict:
    if not repo:
        return {}
    data = _get_json(f"{HF}/{repo}/resolve/main/config.json")
    return data if isinstance(data, dict) and not data.get("__error__") else {}


def main():
    candidates = json.loads(open(sys.argv[1], encoding="utf-8").read())
    out = []
    fails = []
    for c in candidates:
        search = c.pop("_search")
        official = c.pop("_official_author", None)
        config_repo = c.get("hf_repo")
        repo = c.pop("_gguf_repo", None) or find_gguf_repo(search, official)
        if not repo:
            fails.append((c["id"], "no se encontró repo GGUF"))
            continue
        tmpl, tok, multipart = derive_template(repo)
        if not tmpl:
            fails.append((c["id"], f"sin .gguf (ni single ni shards) en {repo}"))
            continue
        # Single-file: verificar que el Q4_K_M concreto resuelve. Multi-parte: ya verificado
        # por derive_template (encontró los shards), el single-file no existe a propósito.
        if not multipart:
            test_file = tmpl.format(quant="Q4_K_M")
            if not _head_ok(f"{HF}/{repo}/resolve/main/{test_file}"):
                if not _head_ok(f"{HF}/{repo}/resolve/main/{tmpl.format(quant=tok)}"):
                    fails.append((c["id"], f"Q4_K_M no resuelve en {repo}"))
                    continue
        cfg = fetch_config(config_repo)
        n_layer = cfg.get("num_hidden_layers") or cfg.get("n_layers") or c.get("n_layer")
        max_ctx = cfg.get("max_position_embeddings") or c.get("max_ctx")
        n_head = cfg.get("num_attention_heads") or cfg.get("n_heads")
        n_head_kv = cfg.get("num_key_value_heads") or n_head  # sin GQA: KV = nº cabezas
        head_dim = cfg.get("head_dim") or (
            (cfg["hidden_size"] // n_head) if (cfg.get("hidden_size") and n_head) else None
        )
        c["hf_gguf"] = {"repo": repo, "file_template": tmpl}
        if multipart:
            c["hf_gguf"]["multipart"] = True
        if n_layer:
            c["n_layer"] = int(n_layer)
        if max_ctx:
            c["max_ctx"] = int(max_ctx)
        # Dims de arquitectura para la KV-cache exacta (captura GQA/MQA)
        if n_head:
            c["n_head"] = int(n_head)
        if n_head_kv:
            c["n_head_kv"] = int(n_head_kv)
        if head_dim:
            c["head_dim"] = int(head_dim)
        c.setdefault("size_base_gb", round(c["params_b"] * 2, 1))
        out.append(c)
        print(f"OK  {c['id']:32s} -> {repo}  tmpl={tmpl}  ctx={max_ctx} layers={n_layer}", file=sys.stderr)

    for fid, why in fails:
        print(f"FAIL {fid:31s} {why}", file=sys.stderr)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    import urllib.parse
    main()

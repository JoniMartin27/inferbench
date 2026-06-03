"""Enriquece data/models.json con dims de arquitectura para la KV-cache exacta.

Rellena n_head, n_head_kv (GQA/MQA) y head_dim de cada modelo del catálogo desde
fuentes verificables (sin inventar nada):

  1. Header del GGUF abierto (hf_gguf.repo) vía HTTP Range — la fuente exacta: es
     el mismo archivo que llama.cpp carga. Funciona incluso para modelos cuyo repo
     original está gated (bartowski/lmstudio los republican abiertos). Bastan ~256KB.
  2. Fallback: config.json del hf_repo (para los que no tienen hf_gguf y no están gated).

Idempotente: por defecto solo rellena los que faltan.

  python scripts/enrich_arch.py            # rellena faltantes in-place
  python scripts/enrich_arch.py --force    # recalcula todos
  python scripts/enrich_arch.py --dry-run  # reporta sin escribir
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import gguf_reader  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data" / "models.json"
HF = "https://huggingface.co"
UA = {"User-Agent": "inferbench-enrich"}
RANGES = (262_144, 1_048_576, 4_194_304)  # 256KB → 1MB → 4MB (escala si el header es grande)


def _arch_dims(meta: dict) -> dict | None:
    """Extrae n_layer/n_head/n_head_kv/head_dim de la metadata GGUF (con prefijo de arch).

    Usa attention.key_length como head_dim (la dimensión real de K/V), cayendo a
    embedding_length // head_count cuando no está. n_head_kv < n_head indica GQA.
    """
    arch = meta.get("general.architecture", "")
    n_layer = meta.get(f"{arch}.block_count")
    n_head = meta.get(f"{arch}.attention.head_count")
    n_head_kv = meta.get(f"{arch}.attention.head_count_kv") or n_head
    n_embd = meta.get(f"{arch}.embedding_length")
    head_dim = meta.get(f"{arch}.attention.key_length") or (
        (n_embd // n_head) if (n_embd and n_head) else None
    )
    if not (n_layer and n_head and n_head_kv and head_dim):
        return None
    return {"n_layer": int(n_layer), "n_head": int(n_head),
            "n_head_kv": int(n_head_kv), "head_dim": int(head_dim)}


def _range_fetch(url: str, nbytes: int, timeout: int = 40) -> bytes | None:
    req = urllib.request.Request(url, headers={**UA, "Range": f"bytes=0-{nbytes - 1}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


def from_gguf(repo: str, file_template: str) -> dict | None:
    fn = file_template.format(quant="Q4_K_M")
    url = f"{HF}/{repo}/resolve/main/{fn}"
    tf = Path(tempfile.gettempdir()) / "ib_enrich.gguf"
    for nbytes in RANGES:
        buf = _range_fetch(url, nbytes)
        if not buf:
            return None  # red caída / archivo inexistente
        try:
            tf.write_bytes(buf)
            meta = gguf_reader.read_gguf_metadata(tf, max_header_bytes=len(buf))
            dims = _arch_dims(meta)
            if dims:
                return dims
        except Exception:
            pass  # header truncado a este tamaño → probar el siguiente rango
    return None


def from_config(hf_repo: str | None) -> dict | None:
    if not hf_repo:
        return None
    try:
        req = urllib.request.Request(f"{HF}/{hf_repo}/resolve/main/config.json", headers=UA)
        with urllib.request.urlopen(req, timeout=15) as r:
            cfg = json.loads(r.read().decode())
    except Exception:
        return None  # gated (401) o sin config
    n_head = cfg.get("num_attention_heads")
    if not n_head:
        return None
    n_head_kv = cfg.get("num_key_value_heads") or n_head
    head_dim = cfg.get("head_dim") or (
        cfg["hidden_size"] // n_head if cfg.get("hidden_size") else None
    )
    if not head_dim:
        return None
    return {"n_layer": cfg.get("num_hidden_layers"), "n_head": int(n_head),
            "n_head_kv": int(n_head_kv), "head_dim": int(head_dim)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="recalcula incluso los ya rellenos")
    ap.add_argument("--dry-run", action="store_true", help="no escribe, solo reporta")
    args = ap.parse_args()

    models = json.loads(DATA.read_text(encoding="utf-8"))
    done = skipped = failed = 0
    for m in models:
        if m.get("n_head_kv") and m.get("head_dim") and not args.force:
            skipped += 1
            continue
        gg = m.get("hf_gguf")
        dims = from_gguf(gg["repo"], gg["file_template"]) if gg else None
        if not dims:
            dims = from_config(m.get("hf_repo"))
        if not dims:
            failed += 1
            print(f"FAIL {m['id']:30s} sin dims (gated/sin fuente abierta)", file=sys.stderr)
            continue
        # Sanity: el n_layer de la fuente debe coincidir con el del catálogo.
        cat_nl, src_nl = m.get("n_layer"), dims.get("n_layer")
        if cat_nl and src_nl and cat_nl != src_nl:
            print(f"WARN {m['id']:30s} n_layer catálogo={cat_nl} != fuente={src_nl}",
                  file=sys.stderr)
        m["n_head"] = dims["n_head"]
        m["n_head_kv"] = dims["n_head_kv"]
        m["head_dim"] = dims["head_dim"]
        done += 1
        ratio = dims["n_head"] / dims["n_head_kv"]
        kind = f"GQA {ratio:.0f}x" if ratio > 1 else "MHA"
        print(f"OK   {m['id']:30s} n_head={dims['n_head']:>3} n_head_kv={dims['n_head_kv']:>3} "
              f"head_dim={dims['head_dim']:>3}  ({kind})", file=sys.stderr)

    print(f"\nEnriquecidos {done} · saltados {skipped} · fallidos {failed}", file=sys.stderr)
    if done and not args.dry_run:
        DATA.write_text(json.dumps(models, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Escrito {DATA}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

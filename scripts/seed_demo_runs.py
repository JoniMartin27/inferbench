"""Seed two REAL benchmark runs for the demo recording (see docs/DEMO-GUION.md).

Runs the SAME model with two quants (Q8_0 and Q4_K_M) over a prompt subset the
model actually handles well (chat / summary / long-context) so no quality cell
shows 0 in the Results table or the History comparison chart. These are real
llama.cpp benchmarks against the cached GGUFs -- no invented numbers (project
rule: no simulated data outside unit tests).

Scene 4 of the storyboard picks these two runs by their `notes` and compares
them, so the answer on screen is the one everybody actually asks: is Q8 worth
it over Q4 on my machine?

Usage: python scripts/seed_demo_runs.py [model-id]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:7777"
MODEL = sys.argv[1] if len(sys.argv) > 1 else "llama-3.2-1b"
PROMPTS = ["chat", "summary", "long-context"]
QUANTS = ["Q8_0", "Q4_K_M"]
NOTE = "demo {quant}"


def post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def stream_until_done(run_id: str, timeout_s: int = 600) -> None:
    """Consume the SSE stream until the run finishes (or timeout)."""
    url = f"{BASE}/api/benchmark/{run_id}/stream"
    req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
    started = time.time()
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        for raw in r:
            if time.time() - started > timeout_s:
                print("  [timeout]")
                return
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if not payload:
                continue
            try:
                ev = json.loads(payload)
            except json.JSONDecodeError:
                continue
            t = ev.get("type")
            if t == "phase":
                print(f"  phase: {ev.get('phase')} {ev.get('detail','')}")
            elif t == "result":
                print(f"  result: {ev.get('prompt_id')} tps={ev.get('tps')} ttft={ev.get('ttft_ms')} Q={ev.get('quality')}")
            elif t in ("done", "complete", "finished"):
                print("  [done]")
                return
            elif t == "error":
                print(f"  ERROR: {ev.get('text') or ev.get('message')}")
        print("  [stream ended]")


def main() -> int:
    run_ids = []
    for q in QUANTS:
        body = {
            "engine": "llamacpp",
            "model": MODEL,
            "quant": q,
            "prompts": PROMPTS,
            "auto": True,
            "keep_alive": False,
            "sampling": {"temperature": 0.3, "top_p": 0.95},
            "notes": NOTE.format(quant=q),
        }
        print(f"== launching {MODEL} {q} prompts={PROMPTS}")
        resp = post("/api/benchmark/run", body)
        rid = resp["run_id"]
        run_ids.append(rid)
        print(f"  run_id={rid}")
        stream_until_done(rid)
        time.sleep(2)
    print("SEED_RUN_IDS=" + ",".join(run_ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())

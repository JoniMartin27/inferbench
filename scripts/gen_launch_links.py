"""Genera LAUNCH-LINKS.html con enlaces de composición pre-rellenados para cada plataforma.
Abres el HTML, clicas un botón y caes en el formulario de la plataforma ya relleno: solo
revisar y darle a Postear. No publica nada por sí mismo.
"""
from pathlib import Path
from urllib.parse import quote

REPO = "https://github.com/JoniMartin27/inferbench"
RELEASE = "https://github.com/JoniMartin27/inferbench/releases/latest"

# --- Reddit r/LocalLLaMA (self post) ---
reddit_title = ("Built a desktop app that downloads, runs and benchmarks local LLM "
                "engines in one click — no Docker, no CLI, open source")
reddit_text = f"""Me cansé de adivinar qué cuantización me entra en la GPU y a cuántos tok/s va a ir, así que construí InferBench: una app de escritorio que, con un click, descarga el binario del motor (release oficial de llama.cpp), baja el GGUF de Hugging Face, arranca el motor con la config óptima para tu hardware y corre una suite de benchmarks midiendo TTFT, tok/s, VRAM y calidad. Mide de verdad — no inventa números.

- 124 modelos verificados en el catálogo (con compatibilidad calculada para TU hardware).
- llama.cpp en modo nativo (sin Docker); Ollama / vLLM / SGLang / TGI vía Docker; + APIs cloud.
- Rigor: descarta una pasada de warmup y reporta la mediana de N muestras + desviación.
- Calidad evaluada con scorers verificables (ejecuta el código que genera el modelo, etc.).
- 100% local. Tus datos no salen del equipo. MIT.

Ejemplo (mi equipo, medido con la propia app): RTX 3070 8GB · Qwen2.5 7B Q4_K_M · 75 tok/s · TTFT 284 ms · 7.96 GB VRAM · calidad 100/100.

Es v0.1.1, binarios para Windows/macOS/Linux en la release. Busco feedback honesto: qué motor/modelo os falta, qué se rompe.

Repo: {REPO}
Descarga: {RELEASE}

(Recuerda adjuntar el GIF de demo en el editor de Reddit antes de postear.)"""
reddit_url = (f"https://www.reddit.com/r/LocalLLaMA/submit?title={quote(reddit_title)}"
              f"&text={quote(reddit_text)}")

# --- Hacker News (Show HN) ---
hn_title = "Show HN: InferBench – Benchmark local LLM engines with one click"
hn_url = f"https://news.ycombinator.com/submitlink?u={quote(REPO)}&t={quote(hn_title)}"

# --- X / Twitter (tweet 1 del hilo) ---
tweet1 = (f"¿Quieres correr LLMs en local pero no sabes qué cuantización te entra en la GPU "
          f"ni a cuántos tok/s va a ir? Hice una app de escritorio que lo mide por ti con un "
          f"click. Open source, sin Docker, sin CLI. 🧵 {REPO}")
x_url = f"https://twitter.com/intent/tweet?text={quote(tweet1)}"

# --- dev.to (no admite prefill por URL: abre el editor vacío) ---
devto_url = "https://dev.to/new"

CARDS = [
    ("1 · r/LocalLLaMA", "El de mayor ROI. Cae en el editor con título y cuerpo ya puestos. "
     "Adjunta el GIF y dale a Post. Flair: Resources.", reddit_url, "Abrir Reddit pre-relleno"),
    ("2 · Hacker News — Show HN", "Cae en submit con URL y título puestos. Tras enviar, pega "
     "tu primer comentario (lo tienes en LAUNCH-POSTS.md).", hn_url, "Abrir Show HN pre-relleno"),
    ("3 · X / Twitter", "Abre el composer con el tweet 1 del hilo. Publica y añade los tweets "
     "2-4 como respuestas (en LAUNCH-POSTS.md). Adjunta el GIF al tweet 1.", x_url,
     "Abrir tweet pre-relleno"),
    ("4 · dev.to", "No admite prefill: abre el editor vacío. Pega el artículo desde "
     "LAUNCH-POSTS.md.", devto_url, "Abrir editor dev.to"),
]

rows = "\n".join(
    f"""  <div class="card">
    <h2>{t}</h2>
    <p>{d}</p>
    <a class="btn" href="{u}" target="_blank" rel="noopener">{label} ↗</a>
  </div>""" for (t, d, u, label) in CARDS
)

html = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>InferBench — lanzar posts</title>
<style>
  body {{ font-family: system-ui, sans-serif; background:#0f172a; color:#e2e8f0;
         max-width:760px; margin:0 auto; padding:32px 20px; }}
  h1 {{ font-size:1.5rem; }} p.sub {{ color:#94a3b8; }}
  .card {{ background:#1e293b; border:1px solid #334155; border-radius:12px;
           padding:18px 20px; margin:16px 0; }}
  .card h2 {{ margin:0 0 6px; font-size:1.1rem; }}
  .card p {{ margin:0 0 14px; color:#cbd5e1; font-size:.95rem; }}
  .btn {{ display:inline-block; background:#6366f1; color:#fff; text-decoration:none;
          padding:10px 16px; border-radius:8px; font-weight:600; }}
  .btn:hover {{ background:#4f46e5; }}
  .note {{ color:#94a3b8; font-size:.85rem; margin-top:24px; }}
</style></head><body>
  <h1>🚀 Lanzar InferBench v0.1.1 — un clic por canal</h1>
  <p class="sub">Cada botón abre la plataforma con el post ya escrito. Revisa, adjunta el GIF
  donde toque y dale a Postear. <b>Lanza un canal por día.</b> Nada se publica solo.</p>
{rows}
  <p class="note">Los textos completos (hilo de X, primer comentario de HN, artículo dev.to)
  están en <code>LAUNCH-POSTS.md</code>. GIF de demo en <code>assets/inferbench-demo.gif</code>.</p>
</body></html>"""

out = Path(__file__).resolve().parent.parent / "LAUNCH-LINKS.html"
out.write_text(html, encoding="utf-8")
print(f"escrito: {out}")

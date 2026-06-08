# Assets del README

Recursos visuales que enlaza el `README.md` principal.

## Actuales

- **`inferbench-demo.gif`** — GIF de cabecera (900×563, ~32s, recorrido completo: Dashboard → Modelos/Optimizar → **Benchmark en vivo** → Comparar runs → Serve/MCP + imagen). Es el que muestra el `README.md`. Validado fotograma a fotograma (PR #8).
- **`inferbench-run.gif`** — clip corto (~7.5s) centrado en el **panel de ejecución en vivo** del benchmark (log de fases + tok/s subiendo por SSE). Recorte del segmento de benchmark del GIF de cabecera, así que refleja el mismo recorrido actual.
- **`screenshot-dashboard.png`** — captura estática del Dashboard (fallback si el GIF no carga).
- **`screenshot-models.png`** — vista Models: catálogo + optimización automática (la vista que mejor vende el producto).

Los PNG y el clip se derivan de `inferbench-demo.gif`, así que **siempre reflejan el mismo recorrido que el GIF de cabecera**.

## Re-grabar / regenerar

Tras regrabar `inferbench-demo.gif`, regenera los derivados con ffmpeg (selección por timestamp, robusta ante cambios de fps):

```bash
# Fallbacks estáticos (ajusta los segundos a las escenas Dashboard / Models del nuevo GIF)
ffmpeg -y -ss 2   -i inferbench-demo.gif -frames:v 1 screenshot-dashboard.png
ffmpeg -y -ss 5.5 -i inferbench-demo.gif -frames:v 1 screenshot-models.png

# Clip corto del benchmark en vivo (recorta el tramo de la escena Benchmark)
ffmpeg -y -ss 9 -t 7.5 -i inferbench-demo.gif \
  -vf "fps=12,scale=900:-1:flags=lanczos,palettegen=stats_mode=diff" palette.png
ffmpeg -y -ss 9 -t 7.5 -i inferbench-demo.gif -i palette.png \
  -lavfi "fps=12,scale=900:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3" inferbench-run.gif
```

El GIF de cabecera se regraba con el pipeline reproducible del repo: `scripts/seed_demo_runs.py` (siembra runs reales) + `scripts/record-demo.mjs` (Playwright → ffmpeg). Mantén el ancho del GIF de cabecera a 900px y el peso < 8 MB para que cargue rápido en GitHub.

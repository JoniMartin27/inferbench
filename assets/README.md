# Assets del README

Recursos visuales que enlaza el `README.md` principal.

## Actuales

- **`inferbench-promo.gif`** — GIF de cabecera actual (900×540, ~20s, 20 fps, 2,1 MB). Promo motion-graphics en inglés generado programáticamente (Pillow + ffmpeg): logo → "Stop guessing" → pipeline one-click → panel de métricas reales (588 ms TTFT, 272 tok/s, 2.47 GB VRAM, 75/100 en RTX 3070) → features → end card. Es el que muestra el `README.md` como hero.
- **`inferbench-demo.gif`** — demo real de la app (**800×500, 38,8 s, 8 fps, 48 colores, 6,5 MB**; regrabada el 2026-08-13). Recorrido: Dashboard → Modelos/Optimizar → **Benchmark en vivo + fila de resultados** → Comparar runs → Serve/MCP con generación de imagen real. Enlazado en el `README.md` dentro de un `<details>` bajo el hero.
- **`inferbench-run.gif`** — clip corto (800×500, ~8 s) centrado en el **panel de ejecución en vivo** del benchmark (arranque del motor + log de fases + tok/s subiendo por SSE). Recorte del tramo de benchmark del GIF de la demo, así que refleja el mismo recorrido actual.
- **`screenshot-dashboard.png`** — captura estática del Dashboard (fallback si el GIF no carga).
- **`screenshot-models.png`** — vista Models con el panel de **configuración óptima** abierto (la vista que mejor vende el producto).

Los PNG y el clip se derivan de `inferbench-demo.gif`, así que **siempre reflejan el mismo recorrido que la demo**.

## Re-grabar / regenerar

El guion manda: **[`docs/DEMO-GUION.md`](../docs/DEMO-GUION.md)** tiene la escaleta escena a escena, los criterios de aceptación, las precondiciones y las medidas que justifican cada decisión (por qué 8 fps, por qué el quant va a mano, por qué `sd-turbo` se carga cuando se carga). Escribe/actualiza el guion **antes** de grabar.

Resumen del pipeline:

```bash
# 1. Sembrar los dos runs reales que compara la escena 4 (backend en :7777)
backend/.venv/Scripts/python.exe scripts/seed_demo_runs.py llama-3.2-1b

# 2. Grabar (Playwright vive en un directorio aparte para no ensuciar el package.json;
#    la resolución de imports de ESM parte del fichero, así que hay que copiarlo)
cp scripts/record-demo.mjs C:/tmp/pw-runner/
cd C:/tmp/pw-runner && IB_OUT_DIR=C:/tmp/ib-rec node record-demo.mjs   # IB_LANG=es para el corte en castellano

# 3. Montar el GIF cortando los tramos muertos (la lista de cortes vive en el script
#    y está explicada en el guion)
scripts/build-demo-gif.sh C:/tmp/ib-rec/toma.webm assets/inferbench-demo.gif 8 48 800
```

Derivados, con los segundos del GIF nuevo (los de ahora salen de la escaleta del guion):

```bash
ffmpeg -y -ss 0.3  -i inferbench-demo.gif -frames:v 1 screenshot-dashboard.png  # escena 1
ffmpeg -y -ss 9.4  -i inferbench-demo.gif -frames:v 1 screenshot-models.png     # escena 2
ffmpeg -y -ss 12.4 -t 7.0 -i inferbench-demo.gif -filter_complex \
  "fps=8,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3" \
  inferbench-run.gif                                                            # escena 3
```

Mantén el GIF a **800 px** (es el ancho al que lo pinta el README) y **por debajo de 8 MB** para que cargue rápido en GitHub.

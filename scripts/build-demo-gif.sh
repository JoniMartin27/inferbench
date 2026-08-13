#!/usr/bin/env bash
# Monta assets/inferbench-demo.gif a partir de la toma cruda de scripts/record-demo.mjs,
# cortando los tramos que no aportan. La lista de cortes y el porqué de cada parámetro
# están en docs/DEMO-GUION.md — si tocas uno, toca el otro.
#
# No se acelera ningún tramo: lo que queda va a velocidad real.
#
# Uso: scripts/build-demo-gif.sh <toma.webm> <salida.gif> [fps] [colores] [ancho]
set -euo pipefail

V="${1:?falta la toma .webm}"; OUT="${2:?falta el gif de salida}"
FPS="${3:-8}"; COLORS="${4:-48}"; WIDTH="${5:-800}"

# Tramos de la toma que SÍ entran (segundos). Válidos para la toma del 2026-08-13 (la 10);
# si regrabas, sácalos de nuevo MIRANDO fotogramas, no a ojo — entre tomas hay medio
# segundo largo de deriva (lo que tarde el benchmark) y los cortes se notan.
SEGS=(
  "2.0:4.1"    # escena 0 · Guide
  "4.2:7.8"    # escena 1 · Dashboard
  "7.9:14.3"   # escena 2 · Models + panel de configuración óptima
  "18.6:26.9"  # escena 3 · config final del benchmark + run en vivo
  "29.9:32.9"  # escena 3 · fila de RESULTS
  "32.9:39.7"  # escena 4 · History: tabla comparativa entera + gráficas por prompt
  "39.9:43.9"  # escena 5 · Serve/MCP: prompt, Generate y spinner
  "47.1:52.2"  # escena 5 · imagen generada + Connect over MCP
)

filter=""; labels=""; i=0
for s in "${SEGS[@]}"; do
  filter+="[0:v]trim=${s%%:*}:${s##*:},setpts=PTS-STARTPTS[v${i}];"
  labels+="[v${i}]"
  i=$((i + 1))
done
filter+="${labels}concat=n=${i}:v=1:a=0[cat];"
# Paleta en la misma pasada: split -> palettegen -> paletteuse. Sin esto los degradados
# del tema Fervon salen a bandas.
filter+="[cat]fps=${FPS},scale=${WIDTH}:-1:flags=lanczos,split[a][b];"
filter+="[a]palettegen=max_colors=${COLORS}:stats_mode=diff[p];"
filter+="[b][p]paletteuse=dither=bayer:bayer_scale=3[out]"

ffmpeg -y -loglevel error -i "$V" -filter_complex "$filter" -map "[out]" "$OUT"
ls -la "$OUT"
ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT"

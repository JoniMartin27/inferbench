#!/usr/bin/env bash
# Construye el ejecutable del backend con PyInstaller y lo deja en frontend/electron/sidecar/
# Uso (macOS / Linux): bash scripts/build-sidecar.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT/backend"
# Desde uv.lock y con el extra "build": mismas versiones que CI y que el release.
# `--python 3.11` obligatorio: sin él uv elige el intérprete más nuevo instalado.
uv sync --locked --python 3.11 --extra build
uv run pyinstaller pyinstaller.spec --clean --noconfirm

DST="$ROOT/frontend/electron/sidecar"
mkdir -p "$DST"
cp "$ROOT/backend/dist/inferbench-backend" "$DST/inferbench-backend"
chmod +x "$DST/inferbench-backend"
echo "Sidecar listo en $DST"

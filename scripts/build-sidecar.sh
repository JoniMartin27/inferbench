#!/usr/bin/env bash
# Construye el ejecutable del backend con PyInstaller y lo deja en frontend/electron/sidecar/
# Uso (macOS / Linux): bash scripts/build-sidecar.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT/backend"
if [ ! -d .venv ]; then
  uv venv --python 3.11
fi
source .venv/bin/activate
uv pip install pyinstaller >/dev/null
pyinstaller pyinstaller.spec --clean --noconfirm

DST="$ROOT/frontend/electron/sidecar"
mkdir -p "$DST"
cp "$ROOT/backend/dist/inferbench-backend" "$DST/inferbench-backend"
chmod +x "$DST/inferbench-backend"
echo "Sidecar listo en $DST"

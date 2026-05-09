# Construye el ejecutable del backend con PyInstaller y lo deja en frontend/electron/sidecar/
# Uso (Windows): scripts\build-sidecar.ps1
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\.."

Push-Location "$root\backend"
try {
    if (-not (Test-Path .venv)) {
        uv venv --python 3.11
    }
    & .\.venv\Scripts\python.exe -m pip install pyinstaller | Out-Null
    & .\.venv\Scripts\pyinstaller.exe pyinstaller.spec --clean --noconfirm
} finally {
    Pop-Location
}

$src = Join-Path $root "backend\dist\inferbench-backend.exe"
$dst = Join-Path $root "frontend\electron\sidecar"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item -Force $src (Join-Path $dst "inferbench-backend.exe")
Write-Host "Sidecar listo en $dst"

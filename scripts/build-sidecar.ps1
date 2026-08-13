# Construye el ejecutable del backend con PyInstaller y lo deja en frontend/electron/sidecar/
# Uso (Windows): scripts\build-sidecar.ps1
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\.."

# `uv` escribe su progreso en stderr aunque le vaya bien. Con $ErrorActionPreference="Stop",
# PowerShell 5.1 envuelve cada línea de stderr de un ejecutable nativo en un NativeCommandError
# y ABORTA el script con un build perfectamente correcto. Comprobamos el código de salida a
# mano en vez de dejar que la política de errores decida por nosotros.
function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Exe @Arguments 2>&1 | ForEach-Object { Write-Host $_ }
        if ($LASTEXITCODE -ne 0) {
            throw "$Exe $($Arguments -join ' ') salió con código $LASTEXITCODE"
        }
    } finally {
        $ErrorActionPreference = $prev
    }
}

Push-Location "$root\backend"
try {
    # Desde uv.lock y con el extra "build": el sidecar se construye con las MISMAS
    # versiones que valida CI y que usa el workflow de release. `uv sync` crea la venv si
    # falta. El `--python 3.11` es OBLIGATORIO: sin él uv coge el intérprete más nuevo
    # que tenga instalado (aquí 3.14) y el binario saldría con un runtime distinto
    # del que fija el proyecto y valida CI.
    Invoke-Native "uv" @("sync", "--locked", "--python", "3.11", "--extra", "build")
    Invoke-Native "uv" @("run", "pyinstaller", "pyinstaller.spec", "--clean", "--noconfirm")
} finally {
    Pop-Location
}

$src = Join-Path $root "backend\dist\inferbench-backend.exe"
if (-not (Test-Path $src)) { throw "PyInstaller no dejó el exe en $src" }

$dst = Join-Path $root "frontend\electron\sidecar"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item -Force $src (Join-Path $dst "inferbench-backend.exe")

$mb = [math]::Round((Get-Item $src).Length / 1MB, 1)
Write-Host "Sidecar listo en $dst ($mb MB)"

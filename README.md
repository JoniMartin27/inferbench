# InferBench

Panel local multiplataforma para benchmark y comparación de motores de inferencia LLM.

Detecta tu hardware, calcula compatibilidad de modelos, optimiza la configuración automáticamente y ejecuta benchmarks reales contra motores locales (llama.cpp / Ollama / vLLM / SGLang / TGI) y APIs cloud (OpenAI / Anthropic / OpenRouter / NVIDIA NIM).

## Capturas funcionales

- **Dashboard** — estado de hardware, motores y runs históricas
- **Motores** — arrancar/detener contenedores Docker desde la UI con flags por motor
- **Modelos** — tabla de compatibilidad (`GPU` / `MoE offload` / `GPU+RAM` / `CPU` / `No cabe`) + botón ⚡ "Optimizar para mi hardware"
- **Benchmark** — selección de motor + modelo + suite, ejecución live con SSE
- **Historial** — runs persistidas en SQLite con gráficos Recharts
- **Ajustes** — hardware detectado y endpoints

## Requisitos

- **Docker** (para motores locales): https://docs.docker.com/get-docker/
- **Node.js 20+**: https://nodejs.org/
- **Python 3.11+** (sólo en desarrollo o para construir el sidecar)
- **uv** (gestor Python rápido): `curl -LsSf https://astral.sh/uv/install.sh | sh`
- *(Opcional, GPU NVIDIA)* **NVIDIA Container Toolkit** para ejecutar contenedores con GPU

## Desarrollo

```bash
# Backend
cd backend
uv venv --python 3.11
.venv\Scripts\activate    # PowerShell:  .venv\Scripts\Activate.ps1
uv pip install -e .
uvicorn main:app --reload --port 7777

# Frontend (otra terminal)
cd frontend
npm install
npm run electron:dev      # abre Electron + Vite con HMR
```

## Empaquetado (M9)

El backend Python se empaqueta como ejecutable con PyInstaller y se embebe como **sidecar** dentro del instalador Electron. La app, una vez instalada, no requiere Python en la máquina del usuario.

```powershell
# 1. Construir el sidecar
scripts\build-sidecar.ps1     # Windows
# bash scripts/build-sidecar.sh  # macOS / Linux

# 2. Construir el instalador
cd frontend
npm run electron:build
```

Salida en `frontend/release/`:
- Windows → `InferBench Setup *.exe` (NSIS)
- macOS → `InferBench-*.dmg`
- Linux → `InferBench-*.AppImage`

## Documentación

- [PROJECT_BRIEF.md](PROJECT_BRIEF.md) — visión, arquitectura, schemas de optimización por motor, fórmulas de compatibilidad
- [CLAUDE.md](CLAUDE.md) — convenciones e hitos M1–M9

## Estado de hitos

| | Hito | Estado |
|--|------|--------|
| M1 | Detección hardware (CPU/RAM/GPU NVIDIA·AMD·Apple) | ✅ |
| M2 | Gestor Docker + abstracción `Engine` + llama.cpp | ✅ |
| M3 | Catálogo 15 modelos + cálculos de compatibilidad y `max_ctx` | ✅ |
| M4 | Benchmark con SSE + persistencia SQLite + history CRUD | ✅ |
| M5 | Frontend Electron + Vite + Tailwind + cliente HTTP/SSE | ✅ |
| M6 | UI completa (6 vistas, paleta slate-950/indigo-500) | ✅ |
| M7 | Panel live con SSE en `BenchmarkView` | ✅ |
| M8 | Optimizador automático + botón ⚡ por modelo | ✅ |
| M9 | Empaquetado PyInstaller + electron-builder | ✅ (config) |

## Pendientes conocidos / siguientes pasos

- Implementar adaptadores de motor reales para `ollama`, `vllm`, `sglang`, `tgi` (sólo `llamacpp` está en M2; el resto son stubs visibles).
- Sustituir el cálculo de KV-cache por lectura del config del modelo (`n_layer`, `n_kv_heads`, `head_dim`) en lugar de la heurística.
- API keys vía `keyring` del SO (módulo importado pero falta la integración en `engines/openai.py` etc.).
- Quality scoring con LLM-judge en lugar de la heurística MVP por longitud + overlap.
- Tests unitarios en `core/compat.py` y `core/optimizer.py`.

# Contribuir a InferBench

¡Gracias por tu interés! Estas son las pautas para contribuir.

## Antes de empezar

- Para cambios grandes (un adaptador de motor nuevo, refactors), **abre un issue antes**
  para acordar el enfoque y no duplicar trabajo.
- Lee [`PROJECT_BRIEF.md`](PROJECT_BRIEF.md) (visión, fórmulas de compatibilidad y schemas
  de optimización por motor) y la sección **Arquitectura** del [`README.md`](README.md).

## Entorno de desarrollo

Requisitos: **Node.js 20+**, **Python 3.11+**, **uv** y (opcional) Docker.

```bash
git clone https://github.com/JoniMartin27/inferbench.git
cd inferbench

# Backend
cd backend
uv venv --python 3.11
uv pip install -e ".[dev]"
uvicorn main:app --reload --port 7777

# Frontend (otra terminal, desde la raíz)
npm install
npm run dev:frontend
```

## Antes de abrir un PR

Tu rama debe pasar lo mismo que el CI:

```bash
# Backend
cd backend
ruff check core api main.py tests   # lint
pytest -q                            # tests

# Frontend (desde la raíz)
npm run build --workspace frontend   # debe compilar sin errores
```

- **Tests**: si añades lógica en `core/` (compat, optimizer, scorer de calidad, lector
  GGUF…), añade o actualiza tests en `backend/tests/`. Son funciones puras → fáciles de testear.
- **Estilo**: Python con `ruff` (línea 100); JSX sin TypeScript (decisión del MVP, no migrar
  sin hablarlo); Tailwind para estilos.
- **No simules datos**: si un motor no está disponible, devuelve un error claro — nunca
  inventes TTFT/tok/s/VRAM. Único mock aceptable: tests unitarios.
- **Catálogo de modelos**: no añadas modelos a mano. Usa `backend/scripts/verify_models.py`
  + `merge_models.py`, que verifican el repo GGUF contra HuggingFace y derivan la metadata real.

## Buenos primeros aportes

- Adaptadores reales para `ollama` / `vllm` / `sglang` / `tgi` (hoy son stubs).
- Más tests para `core/compat.py` y `core/optimizer.py`.
- Verificación de checksum de los binarios descargados (ver `SECURITY-AUDIT.md`).

## Commits y PRs

- Mensajes de commit descriptivos (estilo `tipo(scope): resumen`, p.ej. `feat(catalog): …`).
- Un PR = un cambio coherente. Describe el qué y el porqué, y enlaza el issue si lo hay.

## Licencia

Al contribuir, aceptas que tu aporte se publique bajo la licencia [MIT](LICENSE) del proyecto.

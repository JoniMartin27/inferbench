<!-- Gracias por contribuir a InferBench -->

## Qué hace este PR

<!-- Describe el cambio y el porqué. Enlaza el issue si lo hay (Fixes #123). -->

## Tipo de cambio

- [ ] Bug fix
- [ ] Nueva feature
- [ ] Refactor / mantenimiento
- [ ] Docs

## Checklist

- [ ] `ruff check core api main.py tests` pasa (backend)
- [ ] `pytest -q` pasa (backend)
- [ ] `npm run build --workspace frontend` compila (frontend)
- [ ] He añadido/actualizado tests si toqué lógica en `core/`
- [ ] No introduzco datos simulados (TTFT/tok/s/VRAM) fuera de tests
- [ ] Si añadí modelos al catálogo, usé `backend/scripts/verify_models.py`

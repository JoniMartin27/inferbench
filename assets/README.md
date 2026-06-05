# Assets del README

Recursos visuales que enlaza el `README.md` principal.

## Actuales

- **`inferbench-demo.gif`** — GIF de cabecera (recorrido completo: Modelos → Optimizar → Benchmark en vivo → Comparar). Es el que muestra el README.
- **`inferbench-run.gif`** — alternativa más corta centrada en el panel de ejecución en vivo.
- **`screenshot-dashboard.png`** — captura estática del Dashboard (fallback si el GIF no carga).
- **`screenshot-models.png`** — catálogo de modelos con compatibilidad por motor + optimización automática (la vista que mejor vende el producto).

Los PNG se extrajeron de `inferbench-demo.gif` con ffmpeg, así que siempre reflejan el mismo recorrido que el GIF.

## Re-grabar / regenerar

Para regenerar los PNG de fallback desde el GIF:

```bash
ffmpeg -i inferbench-demo.gif -vf "select=eq(n\,2)" -vframes 1 screenshot-dashboard.png
ffmpeg -i inferbench-demo.gif -vf "select=eq(n\,18)" -vframes 1 screenshot-models.png
```

Para re-grabar el GIF en Windows: ScreenToGif (gratis) o ShareX. Mantén el ancho ≤ 1600px
y el peso < 6 MB para que cargue rápido en GitHub.

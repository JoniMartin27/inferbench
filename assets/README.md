# Assets del README

Coloca aquí los recursos visuales que enlaza el `README.md` principal.

## Pendiente de grabar (lo más importante para conversión)

**`demo.gif`** — el GIF de cabecera. ~10-15 segundos, en bucle. Guion sugerido:

1. Abrir InferBench → vista Modelos (se ve la tabla de compatibilidad con los ⚡).
2. Elegir un modelo + click en **Optimizar** (se autollenan quant/contexto/flags).
3. Click en **Benchmark** → el panel live (RunningPanel) muestra:
   - barra de descarga del binario/GGUF con %,
   - TTFT apareciendo,
   - tok/s subiendo en vivo,
   - log estilo terminal.
4. Ir a Historial → seleccionar 2-3 runs → **Comparar** lado a lado con gráficos.

Herramientas para grabar GIF en Windows: ScreenToGif (gratis, recomendado) o ShareX.
Mantén el ancho ≤ 900px y el peso < 5 MB para que cargue rápido en GitHub.

## Recomendado además

- **`screenshot-dashboard.png`** — captura estática del dashboard (fallback si el GIF no carga).
- **`screenshot-compare.png`** — la vista de comparación con gráficos (es la que más impresiona).

# Política de seguridad

## Versiones con soporte

InferBench está en desarrollo activo (0.x). Solo la última release y la rama `master`
reciben parches de seguridad.

## Reportar una vulnerabilidad

**No abras un issue público para vulnerabilidades.** Usa uno de estos canales privados:

- **GitHub Security Advisories**: pestaña *Security → Report a vulnerability* del repo
  (recomendado, permite divulgación coordinada).
- **Email**: jonathanmartinpaez@gmail.com con asunto `[SECURITY] inferbench`.

Incluye, en lo posible: versión afectada, pasos para reproducir, impacto y, si lo tienes,
una prueba de concepto. Te responderé en un plazo razonable y acordaremos la divulgación.

## Modelo de amenazas (resumen)

InferBench es una app de escritorio local-first. Puntos relevantes:

- **API local en `127.0.0.1:7777`** sin autenticación, capaz de descargar y ejecutar
  binarios de motores. Mitigaciones aplicadas: bind solo a loopback, CORS acotado
  (Vite + `app://.`), y validación de la cabecera `Host` para frenar ataques de
  **DNS-rebinding** (solo se aceptan hosts loopback).
- **Descarga de binarios** de releases de GitHub: los redirects se restringen a hosts
  de GitHub (`github.com`, `*.githubusercontent.com`). Verificación de checksum/firma
  está en el roadmap (ver auditoría).
- **API keys cloud**: viven solo en el estado de React y se envían por request como
  `Bearer`; **nunca** se persisten en disco, SQLite ni localStorage.
- **Electron** corre con `contextIsolation: true`, `nodeIntegration: false`, preload
  mínimo y navegación in-app denegada.

Una auditoría de seguridad completa está en [`SECURITY-AUDIT.md`](SECURITY-AUDIT.md).

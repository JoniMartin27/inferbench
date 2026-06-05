# SECURITY-AUDIT — inferbench

**Fecha auditoría:** 2026-05-29 · **Auditor:** Claude Opus 4.8
**Última actualización:** los 2 hallazgos MEDIUM han sido **remediados** (ver columna *Estado*).

App Electron + React (frontend) y Python/FastAPI (backend `:7777`) que descarga y ejecuta
motores de inferencia locales y llama a APIs cloud.

## Resumen

**Postura muy buena.** Electron correctamente sandboxeado, sin inyección de comandos, sin
secretos persistidos, **0 vulnerabilidades npm**. Los dos hallazgos eran defensa-en-profundidad
de la cadena de suministro / API local, y ya están corregidos.

## Hallazgos

| Sev | Fichero | Descripción | Estado |
|-----|---------|-------------|--------|
| MEDIUM | `core/binary_manager.py` | Descarga binarios de llama.cpp de GitHub releases con `follow_redirects=True` y luego los ejecuta. Un redirect malicioso podría apuntar fuera de GitHub. | ✅ **Remediado**: los redirects se validan contra una allowlist de hosts (`github.com`, `*.githubusercontent.com`) antes y después de seguir redirects, **y** se verifica el SHA-256 del asset contra el `digest` que publica la API de GitHub (mismatch ⇒ borra y aborta; sin digest ⇒ registra el hash calculado). |
| MEDIUM | `main.py` | La API local `:7777` (loopback) no tiene auth y puede descargar+ejecutar binarios. Vector CSRF / DNS-rebinding desde un sitio malicioso. | ✅ **Remediado**: middleware que valida la cabecera `Host` y solo acepta hosts loopback (`localhost`/`127.0.0.1`/`::1`), frenando DNS-rebinding. CORS sigue acotado a Vite + `app://.`. |

## Verificaciones OK (sin hallazgos)

- **Electron** (`frontend/electron/main.js`): `contextIsolation:true`, `nodeIntegration:false`,
  preload mínimo, `setWindowOpenHandler` deniega navegación in-app y abre externos en el
  navegador del sistema. Sidecar lanzado sin shell.
- **FastAPI** (`main.py`): CORS acotado, bind a `127.0.0.1`, validación de Host.
- **Subprocess**: `native_runtime.py`, `hardware.py`, `ollama_manager.py` → **siempre args en
  array, sin shell**. Sin inyección de comandos.
- **API keys cloud**: solo en estado de React, enviadas por request como `Bearer`; **nunca**
  persistidas en SQLite, localStorage ni ficheros (verificado contra el schema de `db.py`).
- **npm audit (frontend + root): 0 vulnerabilidades.**

## Roadmap de hardening

- ✅ ~~Verificación de checksum/firma de los binarios descargados~~ — hecho: SHA-256 contra el `digest` de la API de GitHub en `binary_manager._download_zip`.
- Pin exacto de dependencias Python (hoy usan constraints `>=`).
- Token local opcional para la API `:7777` (defensa adicional a la de `Host`).

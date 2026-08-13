"""El backend no debe colar castellano en lo que ve el usuario.

Convención del proyecto (frontend/src/i18n): "English is the source of truth". La UI
traduce por claves; lo que el backend manda en errores y logs es lo que se pinta cuando no
hay clave, y es también lo que ven los clientes de la API y del MCP.

Este test extiende al RUNNER el contrato que `test_engine_runtimes.py` ya aplica al
`detail` de los motores. Se escribió tras barrer el backend y encontrar **29 cadenas**
visibles al usuario todavía en castellano (mensajes de VRAM, descargas, checksums, Ollama,
gguf_reader…), incluidas dos que había metido yo.

Escanea el AST en vez de grepear: solo mira los sitios que de verdad llegan al usuario
—`raise` de RuntimeError/ValueError/HTTPException y los eventos SSE con clave `text`— y no
los comentarios ni los docstrings, que siguen en castellano a propósito.
"""

import ast
import pathlib
import re

import pytest

# Palabras y signos que delatan castellano. Mismo criterio que `test_engine_runtimes.py`,
# ampliado con lo que apareció en el barrido del runner y los descargadores.
_CASTELLANO = re.compile(
    r"[áéíóúñ¿¡]|\b("
    r"listo|listos|descarga|pendiente|instalado|instalar|arranca|disponible|servidor|"
    r"modelos|propio|calidad|memoria|menos|mayor|permite|solo|cabe|esperando|ocupado|"
    r"fallo|carpeta|fichero|archivo|intentos|abortada|coincide|encontrado|encontraron"
    r")\b",
    re.IGNORECASE,
)

_RAISES = {"RuntimeError", "ValueError", "HTTPException"}

# Sin excepciones: el contrato cubre TODO el backend.
#
# Hubo un allowlist temporal con `core/serve.py` y `core/optimizer.py` mientras otra rama
# los estaba traduciendo. Ya entró, así que se retira. Si alguna vez hace falta volver a
# meter algo aquí, que sea con fecha y motivo — un allowlist permanente convierte este
# test en decoración.
_PENDIENTES: set[str] = set()

_RAIZ = pathlib.Path(__file__).resolve().parent.parent


def _ficheros():
    for f in sorted(_RAIZ.rglob("*.py")):
        rel = f.relative_to(_RAIZ).as_posix()
        if any(p in f.parts for p in ("tests", "scripts", ".venv", "build", "dist")):
            continue
        if rel in _PENDIENTES:
            continue
        yield rel, f


def _textos_visibles(arbol):
    """(línea, texto) de cada literal que acaba delante del usuario."""
    for nodo in ast.walk(arbol):
        candidatos = []
        if isinstance(nodo, ast.Raise) and isinstance(nodo.exc, ast.Call):
            nombre = getattr(nodo.exc.func, "id", getattr(nodo.exc.func, "attr", ""))
            if nombre in _RAISES:
                candidatos = list(nodo.exc.args)
        elif isinstance(nodo, ast.Dict):
            claves = [getattr(k, "value", None) for k in nodo.keys]
            if "text" in claves:
                candidatos = [nodo.values[claves.index("text")]]
        for c in candidatos:
            if isinstance(c, ast.Constant) and isinstance(c.value, str):
                yield nodo.lineno, c.value
            elif isinstance(c, ast.JoinedStr):  # f-string: nos quedan los trozos literales
                literal = "".join(
                    v.value
                    for v in c.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)
                )
                if literal:
                    yield nodo.lineno, literal


@pytest.mark.parametrize(
    "rel,fichero", list(_ficheros()), ids=lambda x: x if isinstance(x, str) else ""
)
def test_los_mensajes_al_usuario_van_en_ingles(rel, fichero):
    arbol = ast.parse(fichero.read_text(encoding="utf-8"))
    colados = [
        (ln, _CASTELLANO.search(txt).group(0), txt.strip()[:70])
        for ln, txt in _textos_visibles(arbol)
        if _CASTELLANO.search(txt)
    ]
    assert not colados, "castellano en mensajes que ve el usuario:\n" + "\n".join(
        f"  {rel}:{ln}  [{palabra}]  {muestra}" for ln, palabra, muestra in colados
    )


def test_el_detector_reconoce_castellano_de_verdad():
    """Si el detector no detecta, el test de arriba es decorativo."""
    assert _CASTELLANO.search("no cabe en la memoria disponible")
    assert _CASTELLANO.search("Ningún prompt es ejecutable")
    assert _CASTELLANO.search("Descarga abortada")
    assert _CASTELLANO.search("no se encontró el fichero")


def test_el_detector_no_marca_ingles_normal():
    """Y si marcase inglés corriente, el test de arriba sería ruido."""
    for bueno in (
        "does not fit in the VRAM available for vllm: it needs ~2.0 GB",
        "No prompt can run with this combination (skipped: vision-scene).",
        "SHA-256 checksum mismatch for llama.cpp: download aborted.",
        "Ollama is not installed. Install it from https://ollama.com/download",
    ):
        assert _CASTELLANO.search(bueno) is None, f"falso positivo en: {bueno}"

"""Tests del gating de visión para GGUFs de disco.

El fallo que fijan: un Qwen2-VL **local** no está en el catálogo, así que no lleva el tag
`vision`. El bootstrap sí encontraba su `mmproj` hermano y arrancaba llama-server con
`--mmproj` (o sea el motor era multimodal), pero el gate seguía diciendo que no: el prompt
de imagen se omitía y el run terminaba SIN un solo resultado y SIN error. Desde fuera
parecía que "el benchmark va bien pero no sale nada" — el síntoma reportado como
"no puedo lanzar modelos de visión".
"""

import pytest

from core import benchmark as bm
from core import local_models as lm


@pytest.fixture
def carpeta(tmp_path):
    d = tmp_path / "modelos"
    d.mkdir()
    return d


def _gguf(dir_, nombre):
    p = dir_ / nombre
    p.write_bytes(b"x" * 64)
    return p


# --- el gate del runner ---------------------------------------------------------------


def test_local_con_mmproj_hermano_admite_imagenes(carpeta):
    modelo = _gguf(carpeta, "Qwen2-VL-2B-Instruct-Q4_K_M.gguf")
    _gguf(carpeta, "mmproj-Qwen2-VL-2B-Instruct-f16.gguf")

    # `model=None`: un GGUF de disco NO existe en el catálogo. Antes esto bastaba para
    # denegar la visión aunque el motor fuese a cargar el projector.
    assert bm.supports_vision("llamacpp", None, str(modelo)) is True


def test_local_sin_mmproj_no_admite_imagenes(carpeta):
    modelo = _gguf(carpeta, "SmolLM2-360M-Instruct-Q4_K_M.gguf")
    assert bm.supports_vision("llamacpp", None, str(modelo)) is False


def test_sin_ruta_local_se_comporta_como_antes():
    """Sin `local_path` manda el catálogo; las APIs cloud siguen pasando siempre."""
    assert bm.supports_vision("llamacpp", None) is False
    assert bm.supports_vision("openai", None) is True


def test_el_catalogo_sigue_mandando_para_modelos_descargados(carpeta):
    """Un modelo de catálogo con tag vision no depende de que haya mmproj en disco."""

    class _M:
        is_vision = True

    assert bm.supports_vision("llamacpp", _M()) is True


# --- emparejado de projectors en el escaneo local ---------------------------------------


def test_el_escaneo_marca_projector_y_empareja_mmproj(carpeta, monkeypatch, tmp_path):
    estado = tmp_path / "estado"
    estado.mkdir()
    monkeypatch.setattr(lm, "all_search_dirs", lambda: [carpeta])
    monkeypatch.setattr(lm, "_state_dir", lambda: estado)
    lm.clear_meta_cache()

    _gguf(carpeta, "Qwen2-VL-2B-Instruct-Q4_K_M.gguf")
    _gguf(carpeta, "mmproj-Qwen2-VL-2B-Instruct-f16.gguf")

    encontrados = {m.filename: m for m in lm.discover(read_metadata=False)}
    modelo = encontrados["Qwen2-VL-2B-Instruct-Q4_K_M.gguf"]
    projector = encontrados["mmproj-Qwen2-VL-2B-Instruct-f16.gguf"]

    assert projector.is_projector is True, "un mmproj no es un modelo ejecutable"
    assert projector.mmproj is None, "un projector no se empareja consigo mismo"
    assert modelo.is_projector is False
    assert modelo.mmproj == projector.path, "el modelo debe apuntar a su projector"
    lm.clear_meta_cache()


def test_un_modelo_solo_en_su_carpeta_no_se_marca_como_vision(carpeta, monkeypatch, tmp_path):
    estado = tmp_path / "estado"
    estado.mkdir()
    monkeypatch.setattr(lm, "all_search_dirs", lambda: [carpeta])
    monkeypatch.setattr(lm, "_state_dir", lambda: estado)
    lm.clear_meta_cache()

    _gguf(carpeta, "SmolLM2-360M-Instruct-Q4_K_M.gguf")
    (modelo,) = lm.discover(read_metadata=False)

    assert modelo.is_projector is False
    assert modelo.mmproj is None
    lm.clear_meta_cache()


def test_el_projector_se_detecta_tambien_por_arquitectura():
    """Si alguien renombra el fichero, la cabecera GGUF sigue diciendo `clip`."""
    m = lm.LocalModel(
        path="/x/proyector.gguf", filename="proyector.gguf", dir="/x", size_gb=0.5,
        architecture="clip",
    )
    assert lm._es_projector(m) is True

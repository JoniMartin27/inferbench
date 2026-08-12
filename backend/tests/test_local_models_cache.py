"""Tests de la caché de metadata GGUF en core/local_models.py.

Contexto (medido sobre 28 GGUFs reales): el rglob de las carpetas conocidas cuesta 5 ms y
leer las cabeceras GGUF 5,7 s — el 99,7% del coste. Como las vistas piden el listado en
cada montaje, sin caché se releía todo al cambiar de pestaña. La caché es POR FICHERO y
con el rglob siempre en vivo; estos tests fijan justo eso: que acelera SIN mentir sobre
lo que hay en disco.
"""

from pathlib import Path

import pytest

from core import local_models as lm


@pytest.fixture
def escaneo_aislado(tmp_path, monkeypatch):
    """Aísla el escaneo y la caché a tmp_path: ni toca el disco real ni el %APPDATA% real."""
    modelos = tmp_path / "modelos"
    modelos.mkdir()
    estado = tmp_path / "estado"
    estado.mkdir()

    monkeypatch.setattr(lm, "all_search_dirs", lambda: [modelos])
    monkeypatch.setattr(lm, "_state_dir", lambda: estado)
    lm.clear_meta_cache()
    yield modelos
    lm.clear_meta_cache()


def _gguf(dir_: Path, nombre: str, contenido: bytes = b"x" * 64) -> Path:
    p = dir_ / nombre
    p.write_bytes(contenido)
    return p


@pytest.fixture
def contador_lecturas(monkeypatch):
    """Cuenta cuántas veces se lee de verdad una cabecera GGUF."""
    llamadas: list[str] = []
    original = lm._enrich_with_metadata

    def espia(m):
        llamadas.append(m.path)
        m = original(m)
        # Marcamos algo comprobable: el .gguf de prueba no es un GGUF real, así que
        # _enrich_with_metadata deja `error`. Nos vale para verificar que se cachea.
        m.architecture = m.architecture or "arch-de-prueba"
        return m

    monkeypatch.setattr(lm, "_enrich_with_metadata", espia)
    return llamadas


def test_segunda_pasada_no_relee_cabeceras(escaneo_aislado, contador_lecturas):
    _gguf(escaneo_aislado, "a-Q4_K_M.gguf")
    _gguf(escaneo_aislado, "b-Q8_0.gguf")

    primera = lm.discover(read_metadata=True)
    assert len(primera) == 2
    assert len(contador_lecturas) == 2, "la primera pasada debe leer ambas cabeceras"

    segunda = lm.discover(read_metadata=True)
    assert len(segunda) == 2
    assert len(contador_lecturas) == 2, "la segunda pasada no debe releer ninguna cabecera"
    # Y devuelve lo mismo, no un listado empobrecido.
    assert [m.architecture for m in segunda] == [m.architecture for m in primera]


def test_modelo_nuevo_aparece_sin_pedir_refresco(escaneo_aislado, contador_lecturas):
    """El rglob se hace SIEMPRE: la caché no puede ocultar un GGUF recién descargado."""
    _gguf(escaneo_aislado, "a-Q4_K_M.gguf")
    assert len(lm.discover(read_metadata=True)) == 1

    _gguf(escaneo_aislado, "b-Q8_0.gguf")
    encontrados = lm.discover(read_metadata=True)

    assert len(encontrados) == 2, "un modelo nuevo debe verse sin refresh"
    assert len(contador_lecturas) == 2, "y solo debe leerse la cabecera del nuevo"


def test_modelo_borrado_desaparece(escaneo_aislado, contador_lecturas):
    a = _gguf(escaneo_aislado, "a-Q4_K_M.gguf")
    _gguf(escaneo_aislado, "b-Q8_0.gguf")
    assert len(lm.discover(read_metadata=True)) == 2

    a.unlink()
    encontrados = lm.discover(read_metadata=True)

    assert [m.filename for m in encontrados] == ["b-Q8_0.gguf"]


def test_fichero_reemplazado_se_vuelve_a_leer(escaneo_aislado, contador_lecturas):
    """La clave lleva tamaño y mtime: si el .gguf cambia, la metadata cacheada no vale."""
    p = _gguf(escaneo_aislado, "a-Q4_K_M.gguf", b"x" * 64)
    lm.discover(read_metadata=True)
    assert len(contador_lecturas) == 1

    p.write_bytes(b"y" * 4096)  # otro tamaño => otra clave
    lm.discover(read_metadata=True)

    assert len(contador_lecturas) == 2, "un fichero reemplazado debe releerse"


def test_refresh_relee_todo(escaneo_aislado, contador_lecturas):
    _gguf(escaneo_aislado, "a-Q4_K_M.gguf")
    _gguf(escaneo_aislado, "b-Q8_0.gguf")
    lm.discover(read_metadata=True)
    assert len(contador_lecturas) == 2

    lm.discover(read_metadata=True)
    assert len(contador_lecturas) == 2  # cacheado

    lm.discover(read_metadata=True, refresh=True)
    assert len(contador_lecturas) == 4, "refresh=True debe releer todas las cabeceras"


def test_cache_sobrevive_a_reiniciar_el_proceso(escaneo_aislado, contador_lecturas):
    """Se persiste a disco para que abrir la app tampoco pague el escaneo completo."""
    _gguf(escaneo_aislado, "a-Q4_K_M.gguf")
    lm.discover(read_metadata=True)
    assert len(contador_lecturas) == 1

    lm._meta_cache = None  # como si el backend arrancase de cero
    lm.discover(read_metadata=True)

    assert len(contador_lecturas) == 1, "la caché de disco debe evitar releer al arrancar"


def test_cache_corrupta_no_rompe_el_escaneo(escaneo_aislado, contador_lecturas):
    _gguf(escaneo_aislado, "a-Q4_K_M.gguf")
    lm.discover(read_metadata=True)

    lm._meta_cache_file().write_text("{esto no es json", encoding="utf-8")
    lm._meta_cache = None

    encontrados = lm.discover(read_metadata=True)
    assert len(encontrados) == 1, "una caché ilegible debe regenerarse, no tumbar el escaneo"


def test_sin_metadata_no_toca_la_cache(escaneo_aislado, contador_lecturas):
    _gguf(escaneo_aislado, "a-Q4_K_M.gguf")

    encontrados = lm.discover(read_metadata=False)

    assert len(encontrados) == 1
    assert contador_lecturas == [], "read_metadata=False no debe leer cabeceras"
    assert not lm._meta_cache_file().exists(), "ni debe escribir caché"

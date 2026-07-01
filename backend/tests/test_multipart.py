"""Tests de la descarga de GGUF multi-parte (modelos enormes partidos en shards)."""

from core import model_manager
from core.models_catalog import HfGguf, Model


def _model(multipart: bool = True) -> Model:
    return Model(
        id="big",
        name="Big",
        family="x",
        params_b=70.0,
        active_b=70.0,
        is_moe=False,
        size_base_gb=140.0,
        max_ctx=8192,
        hf_gguf=HfGguf(repo="bart/Big-GGUF", file_template="Big-{quant}.gguf", multipart=multipart),
    )


def test_filter_shards_picks_quant_and_sorts():
    # rfilenames reales (estructura de bartowski: subdir por quant)
    base = "Meta-Llama-3.1-70B-Instruct-Q5_K_M"
    files = [
        f"{base}/{base}-00002-of-00002.gguf",
        f"{base}/{base}-00001-of-00002.gguf",
        "Meta-Llama-3.1-70B-Instruct-Q4_K_M.gguf",  # otro quant, single-file
        "README.md",
    ]
    got = model_manager._filter_shards(files, base)
    assert len(got) == 2
    assert got[0].endswith("-00001-of-00002.gguf")  # ordenado por índice
    assert got[1].endswith("-00002-of-00002.gguf")


def test_filter_shards_empty_when_single_file():
    assert model_manager._filter_shards(["Model-Q4_K_M.gguf", "x.txt"], "Model-Q4_K_M") == []


def test_filter_shards_does_not_leak_across_models_with_suffix_overlap():
    # Regresión: sin anclar el inicio del nombre de fichero, un `base` que sea sufijo
    # del nombre de OTRO modelo del mismo repo (ej. 'Model-Q4_K_M' dentro de
    # 'Big-Model-Q4_K_M-...') colaba shards ajenos porque el regex solo anclaba el final.
    base = "Model-Q4_K_M"
    files = [
        "Big-Model-Q4_K_M-00001-of-00002.gguf",  # otro modelo, mismo sufijo — NO debe colar
        "Big-Model-Q4_K_M-00002-of-00002.gguf",
        f"{base}-00001-of-00002.gguf",  # el modelo correcto
        f"{base}-00002-of-00002.gguf",
    ]
    got = model_manager._filter_shards(files, base)
    assert got == [f"{base}-00001-of-00002.gguf", f"{base}-00002-of-00002.gguf"]


def test_multipart_installed_and_path(tmp_path, monkeypatch):
    monkeypatch.setattr(model_manager, "MODELS_ROOT", tmp_path)
    m = _model()
    shard_dir = tmp_path / "bart__Big-GGUF" / "Big-Q4_K_M"
    shard_dir.mkdir(parents=True)

    s1 = shard_dir / "Big-Q4_K_M-00001-of-00002.gguf"
    s1.write_bytes(b"x")
    # Falta la shard 2 → no instalado
    assert model_manager._multipart_installed(m, "Q4_K_M") is False
    assert model_manager.gguf_installed(m, "Q4_K_M") is False

    (shard_dir / "Big-Q4_K_M-00002-of-00002.gguf").write_bytes(b"x")
    # Completos → instalado, y gguf_path apunta a la shard 1
    assert model_manager._multipart_installed(m, "Q4_K_M") is True
    assert model_manager.gguf_installed(m, "Q4_K_M") is True
    assert model_manager.gguf_path(m, "Q4_K_M") == s1


def test_single_file_model_unaffected(tmp_path, monkeypatch):
    monkeypatch.setattr(model_manager, "MODELS_ROOT", tmp_path)
    m = _model(multipart=False)
    assert model_manager.gguf_installed(m, "Q4_K_M") is False  # nada en disco
    p = tmp_path / "bart__Big-GGUF" / "Big-Q4_K_M.gguf"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"x")
    assert model_manager.gguf_installed(m, "Q4_K_M") is True
    assert model_manager.gguf_path(m, "Q4_K_M") == p  # ruta del fichero único

"""Tests del cableado de speculative decoding (DFLASH) en vLLM y SGLang.

Sintaxis tomada de los docs oficiales (no inventada):
  vLLM:   --speculative-config '{"method":"dflash","model":"...","num_speculative_tokens":N}'
          --attention-backend flash_attn
  SGLang: --speculative-algorithm DFLASH --speculative-draft-model-path ... --speculative-num-draft-tokens N
"""
import json

from engines.base import StartRequest
from engines.sglang import SglangEngine
from engines.vllm import VllmEngine


def test_vllm_dflash_config_and_attn_backend():
    eng = VllmEngine()
    cmd = eng.build_command(StartRequest(runtime="docker", engine_opts={
        "hf_model_id": "Qwen/Qwen3.5-27B", "specMethod": "dflash",
        "specDraftModel": "z-lab/Qwen3.5-27B-DFlash", "specNumTokens": 15,
    }))
    cfg = json.loads(cmd[cmd.index("--speculative-config") + 1])
    assert cfg == {
        "method": "dflash",
        "model": "z-lab/Qwen3.5-27B-DFlash",
        "num_speculative_tokens": 15,
    }
    # DFLASH exige flash_attn en vLLM
    assert "--attention-backend" in cmd and cmd[cmd.index("--attention-backend") + 1] == "flash_attn"


def test_vllm_no_spec_without_draft_model():
    eng = VllmEngine()
    cmd = eng.build_command(StartRequest(runtime="docker", engine_opts={"specMethod": "dflash"}))
    assert "--speculative-config" not in cmd  # sin draft no se activa


def test_sglang_dflash_flags():
    eng = SglangEngine()
    cmd = eng.build_command(StartRequest(runtime="docker", engine_opts={
        "hf_model_id": "Qwen/Qwen3.5-35B-A3B", "specMethod": "dflash",
        "specDraftModel": "z-lab/Qwen3.5-35B-A3B-DFlash", "specNumTokens": 16,
    }))
    assert cmd[cmd.index("--speculative-algorithm") + 1] == "DFLASH"  # SGLang lo quiere en mayúsculas
    assert cmd[cmd.index("--speculative-draft-model-path") + 1] == "z-lab/Qwen3.5-35B-A3B-DFlash"
    assert cmd[cmd.index("--speculative-num-draft-tokens") + 1] == "16"


def test_sglang_no_spec_without_draft():
    eng = SglangEngine()
    cmd = eng.build_command(StartRequest(runtime="docker", engine_opts={"specMethod": "dflash"}))
    assert "--speculative-algorithm" not in cmd

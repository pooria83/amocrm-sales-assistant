"""Unit tests for spoken_model() in video/scripts/tts.py.

The video build workspace (video/) is git-ignored, so on a fresh clone this
module does not exist — the tests skip instead of breaking the suite.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TTS_PATH = ROOT / "video" / "scripts" / "tts.py"

if not TTS_PATH.is_file():
    pytest.skip("video build workspace is git-ignored, not present", allow_module_level=True)

SPEC = importlib.util.spec_from_file_location("tts", TTS_PATH)
tts = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(tts)


def test_qwen_2_5_7b() -> None:
    assert tts.spoken_model("qwen2.5:7b") == "квен два-пять"


def test_qwen_3_1() -> None:
    assert tts.spoken_model("qwen3.1") == "квен три-один"


def test_non_qwen_model_unchanged() -> None:
    assert tts.spoken_model("llama3") == "llama3"

"""STEP 7 repo hygiene: tracked text files must contain no CJK/Hangul
characters and no mixed Latin+Cyrillic words."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("check_scripts", ROOT / "eval" / "check_scripts.py")
check_scripts = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(check_scripts)


def test_scanner_finds_planted_violation(tmp_path) -> None:
    bad = tmp_path / "bad.md"
    bad.write_text("Окей but this word is Прerequisites and 답а too\n", encoding="utf-8")
    violations = check_scripts.find_violations([bad])
    kinds = {v.kind for v in violations}
    assert "cjk" in kinds
    assert "mixed" in kinds


def test_tracked_files_have_no_script_violations() -> None:
    violations = check_scripts.find_violations(check_scripts.tracked_text_files())
    details = [f"{v.path}:{v.line} [{v.kind}] {v.text!r}" for v in violations]
    assert violations == [], "\n".join(details)

"""Run retrieval + language eval over eval/cases.yaml (CONTEXT §8).

Usage: uv run python eval/run_eval.py
Prints per-case results, hit@1 / hit@3, grounded accuracy, language accuracy.
Exit code 1 if grounded accuracy < 100% (threshold calibration gate).
"""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.language import detect_language  # noqa: E402
from backend.retriever import get_retriever, get_threshold  # noqa: E402


def main() -> int:
    cases = yaml.safe_load((ROOT / "eval" / "cases.yaml").read_text(encoding="utf-8"))["cases"]
    retriever = get_retriever()
    threshold = get_threshold()

    hit1 = hit3 = 0
    grounded_total = grounded_ok = 0
    lang_total = lang_ok = 0
    rows: list[str] = []

    for case in cases:
        message = case["message"]
        expect = case.get("expect", {})
        history = case.get("history", [])
        ui_lang = case.get("ui_lang", "ru")

        lang, source = detect_language(message, history, ui_lang)
        matches, _, grounded = retriever.retrieve(message)
        ids = [m.entry.id for m in matches]
        scores = [f"{m.entry.id}:{m.score}" for m in matches]

        notes: list[str] = []

        if "lang" in expect:
            lang_total += 1
            if lang == expect["lang"]:
                lang_ok += 1
            else:
                notes.append(f"lang want={expect['lang']} got={lang}")
            if "lang_source" in expect and source != expect["lang_source"]:
                notes.append(f"source want={expect['lang_source']} got={source}")

        if "grounded" in expect:
            grounded_total += 1
            if grounded == expect["grounded"]:
                grounded_ok += 1
            else:
                notes.append(f"grounded want={expect['grounded']} got={grounded}")

        if "ids" in expect:
            expected = expect["ids"]
            if any(e in ids[:1] for e in expected):
                hit1 += 1
            if any(e in ids[:3] for e in expected):
                hit3 += 1
            else:
                notes.append(f"miss top3={ids} want={expected}")

        status = "ok" if not notes else "; ".join(notes)
        rows.append(
            f"{case['id']:<42} {' | '.join(scores) if scores else '-':<50} {status}"
        )

    print(f"threshold={threshold}  cases={len(cases)}")
    for row in rows:
        print(row)

    retrieval_cases = sum(1 for c in cases if "ids" in c.get("expect", {}))
    h1 = hit1 / retrieval_cases if retrieval_cases else 1.0
    h3 = hit3 / retrieval_cases if retrieval_cases else 1.0
    g_acc = grounded_ok / grounded_total if grounded_total else 1.0
    l_acc = lang_ok / lang_total if lang_total else 1.0

    print()
    print(f"hit@1            {hit1}/{retrieval_cases} = {h1:.0%}")
    print(f"hit@3            {hit3}/{retrieval_cases} = {h3:.0%}")
    print(f"grounded acc     {grounded_ok}/{grounded_total} = {g_acc:.0%}")
    print(f"language acc     {lang_ok}/{lang_total} = {l_acc:.0%}")

    return 0 if g_acc >= 1.0 and l_acc >= 1.0 and h3 >= 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

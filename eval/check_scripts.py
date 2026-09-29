"""STEP 7 — repository script hygiene (run 20260929-175559).

Two defect classes found in the run leaked into the docs themselves:
- Chinese characters in tracked markdown (the ru31/x13 replies were quoted
  into mcp/RESULTS.md verbatim);
- accidental mixed-script words such as «Прerequisites» (Cyrillic П + Latin).

This scanner checks every tracked text file (except .py — Python sources
legitimately contain Unicode ranges in regex whitelists and the quoted
defect fixtures themselves; reply-level outputs are covered by the script
whitelist in backend/validators.py instead) for both classes. It is written
in Python on purpose: macOS grep has no -P, so a shell one-liner silently
misses the mixed-script case. Run: python eval/check_scripts.py
(exit 1 on violations). Wired into `make verify` and CI.
"""

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# CJK ideographs, kana, hangul, fullwidth forms (emoji are handled by the
# reply-level script whitelist; in docs they are allowed — only the
# languages this product does not support are violations).
CJK_RE = re.compile(r"[\u2E80-\u9FFF\u3040-\u30FF\uAC00-\uD7AF\uF900-\uFAFF\uFF00-\uFFEF]")
WORD_RE = re.compile(r"[A-Za-z\u0400-\u04FF]+")

TEXT_EXTENSIONS = {
    ".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt", ".cfg", ".ini",
    ".ts", ".tsx", ".js", ".jsx", ".css", ".html", ".sh", ".srt", ".editorconfig",
}


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    kind: str  # "cjk" | "mixed"
    text: str


def tracked_text_files(root: Path = ROOT) -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
        ).stdout
        names = [n for n in out.decode().split("\0") if n]
    except (subprocess.CalledProcessError, FileNotFoundError):
        names = [
            str(p.relative_to(root))
            for p in root.rglob("*")
            if p.is_file() and ".git" not in p.parts
        ]
    files = []
    for name in names:
        path = root / name
        if path.suffix == ".py":
            continue  # regex ranges + quoted fixtures live here by design
        if path.suffix in TEXT_EXTENSIONS and path.is_file():
            files.append(path)
    return files


def find_violations(paths: list[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(lines, 1):
            hit = CJK_RE.search(line)
            if hit:
                violations.append(Violation(path, number, "cjk", hit.group(0)))
            for token in WORD_RE.findall(line):
                if re.search(r"[A-Za-z]", token) and re.search(r"[\u0400-\u04FF]", token):
                    violations.append(Violation(path, number, "mixed", token))
                    break
    return violations


def main() -> int:
    violations = find_violations(tracked_text_files())
    for v in violations:
        print(f"{v.path.relative_to(ROOT)}:{v.line} [{v.kind}] {v.text!r}")
    if violations:
        print(f"{len(violations)} script violation(s) in tracked files", file=sys.stderr)
        return 1
    print("script check: OK (no CJK, no mixed-script words)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""MCP evaluation harness: drives every case through the MCP server.

Two tool calls per case (retrieve_kb → assist_manager), the same ones an MCP
client would make, then evaluates deterministic + content expectations from
mcp/cases.yaml. Every case is logged in full (raw responses included):

  mcp/out/<timestamp>/cases.jsonl   — one JSON object per case (incremental)
  mcp/out/<timestamp>/report.md     — human-readable report (all cases)
  mcp/out/<timestamp>/summary.json  — counts, metrics, failure list
  --md PATH                         — extra copy of the report (e.g. RESULTS.md)

Exit code 0 only when every case passes. Run:  uv run python mcp/run_harness.py
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from mcp.client.stdio import stdio_client

from mcp import ClientSession, StdioServerParameters

ROOT = Path(__file__).resolve().parent.parent
SERVER_PATH = ROOT / "mcp" / "server.py"
DEFAULT_CASES = ROOT / "mcp" / "cases.yaml"

RETRIEVE_TIMEOUT_S = 30.0
ASSIST_TIMEOUT_S = 200.0
HEALTH_TIMEOUT_S = 15.0


class HarnessError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the 100-case MCP evaluation")
    p.add_argument("--base-url", default=os.getenv("APP_BASE_URL", "http://localhost:8000"))
    p.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    p.add_argument("--limit", type=int, default=0, help="run only the first N cases")
    p.add_argument("--offset", type=int, default=0, help="skip the first N cases")
    p.add_argument("--only", default="", help="comma-separated case ids to run")
    p.add_argument("--out", type=Path, default=None, help="output directory")
    p.add_argument("--md", type=Path, default=None, help="also write the report to this path")
    return p.parse_args()


def load_cases(path: Path, limit: int, offset: int, only: str) -> list[dict[str, Any]]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = doc["cases"]
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        raise HarnessError("duplicate case ids in cases.yaml")
    if only:
        wanted: set[str] = set()
        for token in (s.strip() for s in only.split(",") if s.strip()):
            if token in ids:
                wanted.add(token)
                continue
            prefixed = [cid for cid in ids if cid.startswith(token)]
            if not prefixed:
                raise HarnessError(f"unknown case id: {token}")
            wanted.update(prefixed)
        cases = [c for c in cases if c["id"] in wanted]
    if offset:
        cases = cases[offset:]
    if limit:
        cases = cases[:limit]
    return cases


def tool_json(result: Any) -> dict[str, Any]:
    if getattr(result, "isError", False):
        texts = [getattr(c, "text", "") for c in (getattr(result, "content", None) or [])]
        raise HarnessError(f"tool error: {' '.join(texts)[:400]}")
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict) and structured:
        if set(structured) == {"result"} and isinstance(structured["result"], dict):
            return structured["result"]
        return structured
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise HarnessError(f"tool text is not JSON: {text[:200]}") from exc
            if isinstance(data, dict):
                return data
    raise HarnessError("tool returned no JSON object")


def number_tokens(text: str) -> set[str]:
    """Normalized numeric tokens: '1 990'/'1,990' -> '1990', '99,9' -> '99.9'.

    Digits glued to letters (the brand '1C') are not numbers.
    """
    collapsed = re.sub(r"(?<=\d)[\s\u00a0]+(?=\d)", "", text)
    tokens: set[str] = set()
    for tok in re.findall(r"(?<![A-Za-z])\d+(?:[.,]\d+)?(?![A-Za-z])", collapsed):
        if re.fullmatch(r"\d{1,3}[.,]\d{3}", tok):
            tok = tok.replace(",", "").replace(".", "")
        else:
            tok = tok.replace(",", ".")
        tokens.add(tok)
    return tokens


def eq(a: Any, b: Any) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return sorted(map(str, a)) == sorted(map(str, b))
    return a == b


def add(checks: list[dict[str, Any]], name: str, ok: bool, expected: Any = None,
        actual: Any = None) -> None:
    checks.append({"name": name, "ok": bool(ok), "expected": expected, "actual": actual})


def evaluate_expectations(
    expect: dict[str, Any], retrieve: dict[str, Any], assist: dict[str, Any], ui_lang: str
) -> tuple[list[dict[str, Any]], dict[str, bool]]:
    checks: list[dict[str, Any]] = []
    metrics: dict[str, bool] = {}

    reply = assist["customer_reply"]
    hints = assist["internal_sales_hints"]
    validation = assist["validation"]
    fallback = validation["fallback_used"]

    if not fallback:
        for flag in ("schema_ok", "language_ok", "no_leakage", "numbers_ok", "capacity_ok"):
            add(checks, f"validation.{flag}", validation[flag] is True, True, validation[flag])
    add(checks, "reply.lang == detected_lang", reply["lang"] == assist["detected_lang"],
        assist["detected_lang"], reply["lang"])
    add(checks, "hints.lang == ui_lang", hints["lang"] == ui_lang, ui_lang, hints["lang"])
    add(checks, "assist.detected_lang == retrieve.detected_lang",
        assist["detected_lang"] == retrieve["detected_lang"],
        retrieve["detected_lang"], assist["detected_lang"])
    add(checks, "assist.grounded == retrieve.grounded",
        assist["grounded"] == retrieve["grounded"], retrieve["grounded"], assist["grounded"])

    expected_refs = [m["id"] for m in retrieve["matches"] if m["score"] >= retrieve["threshold"]]
    add(checks, "kb_refs == retrieval ids >= threshold", eq(reply["kb_refs"], expected_refs),
        expected_refs, reply["kb_refs"])

    if "lang" in expect:
        add(checks, "lang", assist["detected_lang"] == expect["lang"],
            expect["lang"], assist["detected_lang"])
    if "lang_source" in expect:
        add(checks, "lang_source", retrieve["lang_source"] == expect["lang_source"],
            expect["lang_source"], retrieve["lang_source"])
    if "grounded" in expect:
        add(checks, "grounded", retrieve["grounded"] == expect["grounded"],
            expect["grounded"], retrieve["grounded"])
    if "intent" in expect:
        add(checks, "intent", assist["intent"] == expect["intent"],
            expect["intent"], assist["intent"])

    match_ids = [m["id"] for m in retrieve["matches"]]
    if "ids" in expect:
        want = list(expect["ids"])
        add(checks, "ids@3 (any expected id in top-3)", any(i in match_ids[:3] for i in want),
            want, match_ids)
        metrics["hit_at_1"] = any(i in match_ids[:1] for i in want)

    text = reply["text"]
    folded = text.casefold()
    for needle in expect.get("contains", []):
        add(checks, f"contains {needle!r}", needle.casefold() in folded, needle, text)
    for group in expect.get("contains_any", []):
        hit = next((n for n in group if n.casefold() in folded), None)
        add(checks, f"contains_any {group}", hit is not None, group, hit)
    tokens = number_tokens(text)
    for num in expect.get("contains_numbers", []):
        add(checks, f"contains_number {num}", str(num) in tokens, str(num), sorted(tokens))
    for num in expect.get("forbid_numbers", []):
        add(checks, f"forbid_number {num}", str(num) not in tokens, None, sorted(tokens))

    if "upsell" in expect:
        actual = [h["id"] for h in hints["upsell"]]
        add(checks, "upsell ids (exact set)", eq(actual, list(expect["upsell"])),
            sorted(expect["upsell"]), sorted(actual))
    if "cross_sell" in expect:
        actual = [h["id"] for h in hints["cross_sell"]]
        add(checks, "cross_sell ids (exact set)", eq(actual, list(expect["cross_sell"])),
            sorted(expect["cross_sell"]), sorted(actual))
    if "fallback" in expect:
        add(checks, "fallback_used", fallback == expect["fallback"],
            expect["fallback"], fallback)
    if "notes_contains" in expect:
        needle = expect["notes_contains"]
        add(checks, f"notes_contains {needle!r}", needle.casefold() in hints["notes"].casefold(),
            needle, hints["notes"])

    return checks, metrics


def _deal_line(case: dict[str, Any]) -> str:
    deal = case.get("deal") or {}
    if not deal:
        return "defaults (plan=none, stage=new)"
    return ", ".join(f"{k}={v}" for k, v in deal.items())


def build_report(config: dict[str, Any], results: list[dict[str, Any]]) -> str:
    total = len(results)
    n_pass = sum(1 for r in results if r["verdict"] == "PASS")
    n_fail = sum(1 for r in results if r["verdict"] == "FAIL")
    n_err = sum(1 for r in results if r["verdict"] == "ERROR")
    ids1 = [r for r in results if r["metrics"].get("hit_at_1") is not None]
    hit1 = sum(1 for r in ids1 if r["metrics"]["hit_at_1"])
    hit3 = sum(1 for r in results if any(c["name"].startswith("ids@3") and c["ok"]
                                         for c in r["checks"]))
    grounded_results = [r for r in results if r.get("assist") and r["assist"]["grounded"]]
    latencies = [r["assist"]["validation"]["latency_ms"] for r in grounded_results]
    avg_lat = sum(latencies) / len(latencies) if latencies else 0

    lines = [
        "# MCP Harness — Test Results",
        "",
        f"- Run: `{config['timestamp']}` · base URL: `{config['base_url']}`",
        f"- Cases: `{config['cases_file']}` · model: `{config['model']}` · "
        f"threshold: `{config['threshold']}`",
        f"- **TOTAL {total} · PASS {n_pass} · FAIL {n_fail} · ERROR {n_err}** "
        f"({n_pass / total * 100:.0f}% pass)" if total else "- no cases",
        f"- Retrieval metrics: hit@1 {hit1}/{len(ids1)} · hit@3 {hit3}/{len(ids1)}",
        f"- Avg assist latency (grounded): {avg_lat:.0f} ms",
        "",
        "## Category breakdown",
        "",
        "| category | n | pass | fail | error |",
        "|---|---|---|---|---|",
    ]
    cats: dict[str, list[int]] = {}
    for r in results:
        c = cats.setdefault(r["category"], [0, 0, 0, 0])
        c[0] += 1
        c[{"PASS": 1, "FAIL": 2, "ERROR": 3}[r["verdict"]]] += 1
    for cat in sorted(cats):
        n, p, f, e = cats[cat]
        lines.append(f"| {cat} | {n} | {p} | {f} | {e} |")

    failures = [r for r in results if r["verdict"] != "PASS"]
    if failures:
        lines += ["", "## Failures", ""]
        for r in failures:
            failed = [c["name"] for c in r["checks"] if not c["ok"]]
            reason = r.get("error") or "; ".join(failed)
            lines.append(f"- **{r['id']}** [{r['verdict']}]: {reason}")

    lines += ["", "## Case results", ""]
    for i, r in enumerate(results, 1):
        icon = {"PASS": "✅", "FAIL": "❌", "ERROR": "💥"}[r["verdict"]]
        lines += [f"### {i}. {r['id']} {icon} {r['verdict']} ({r['category']})", ""]
        lines.append(f"- **Message:** «{r['message']}» · ui_lang=`{r['ui_lang']}` · "
                     f"deal: {_deal_line(r['case'])}")
        if r.get("error"):
            lines += [f"- **Error:** {r['error']}", ""]
            continue
        ret, assist = r["retrieve"], r["assist"]
        lines.append(
            f"- **Retrieval:** lang=`{ret['detected_lang']}` "
            f"(source=`{ret['lang_source']}`) · grounded=`{ret['grounded']}` · "
            f"intent=`{assist['intent']}` · threshold=`{ret['threshold']}` · "
            f"{r['retrieve_ms']:.0f} ms"
        )
        if ret["matches"]:
            lines += ["", "| match | score | matched terms |", "|---|---|---|"]
            for m in ret["matches"]:
                lines.append(f"| {m['id']} | {m['score']:.2f} | "
                             f"{', '.join(m['matched_terms'])} |")
        else:
            lines.append("- matches: (none)")
        v = assist["validation"]
        lines += [
            "",
            f"- **Reply** lang=`{assist['customer_reply']['lang']}` · "
            f"kb_refs={assist['customer_reply']['kb_refs']} · "
            f"model=`{v['model'] or '-'}` · {v['latency_ms']} ms · "
            f"retries={v['retries']} · fallback=`{v['fallback_used']}`",
            "",
            "> " + assist["customer_reply"]["text"].replace("\n", "\n> "),
            "",
            f"- **Validation:** schema={'✓' if v['schema_ok'] else '✗'} "
            f"language={'✓' if v['language_ok'] else '✗'} "
            f"numbers={'✓' if v['numbers_ok'] else '✗'} "
            f"capacity={'✓' if v['capacity_ok'] else '✗'} "
            f"leakage={'✓' if v['no_leakage'] else '✗'}",
        ]
        hints = assist["internal_sales_hints"]
        lines.append(f"- **Internal hints** lang=`{hints['lang']}`:")
        for kind in ("upsell", "cross_sell"):
            if hints[kind]:
                for h in hints[kind]:
                    lines.append(f"  - {kind} **{h['id']}** ({h['title']}): "
                                 f"reason: {h['reason']} · talking_point: {h['talking_point']}")
            else:
                lines.append(f"  - {kind}: (none)")
        if hints["notes"]:
            lines.append(f"  - notes: {hints['notes']}")
        failed = [c for c in r["checks"] if not c["ok"]]
        lines.append(f"- **Checks:** {len(r['checks']) - len(failed)}/{len(r['checks'])} passed"
                     + ("" if not failed else " —"))
        for c in failed:
            lines.append(f"  - ❌ `{c['name']}` expected `{c['expected']}`, "
                         f"got `{c['actual']}`")
        if "hit_at_1" in r["metrics"]:
            lines.append(f"- hit@1: {'✓' if r['metrics']['hit_at_1'] else '✗'}")
        lines.append("")
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases, args.limit, args.offset, args.only)
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_dir = args.out or (ROOT / "mcp" / "out" / ts)
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "cases.jsonl"
    report_path = out_dir / "report.md"
    summary_path = out_dir / "summary.json"

    print(f"harness: {len(cases)} cases · base={args.base_url} · out={out_dir}")
    env = {**os.environ, "APP_BASE_URL": args.base_url.rstrip("/")}
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER_PATH)], env=env)
    results: list[dict[str, Any]] = []

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            health = tool_json(await asyncio.wait_for(
                session.call_tool("get_health", arguments={}), HEALTH_TIMEOUT_S))
            print(f"health: {health}")
            if health.get("ollama") != "reachable":
                raise HarnessError(
                    f"Ollama not reachable ({health}); start it and `make warmup` first"
                )

            with jsonl_path.open("w", encoding="utf-8") as jsonl:
                for i, case in enumerate(cases, 1):
                    started = time.monotonic()
                    record: dict[str, Any] = {
                        "id": case["id"], "category": case.get("category", ""),
                        "message": case["message"], "ui_lang": case.get("ui_lang", "ru"),
                        "history": case.get("history", []), "case": case,
                    }
                    try:
                        retrieve = tool_json(await asyncio.wait_for(session.call_tool(
                            "retrieve_kb",
                            arguments={"message": case["message"],
                                       "ui_lang": case.get("ui_lang", "ru"),
                                       "history": case.get("history", [])},
                        ), RETRIEVE_TIMEOUT_S))
                        assist = tool_json(await asyncio.wait_for(session.call_tool(
                            "assist_manager",
                            arguments={"message": case["message"],
                                       "ui_lang": case.get("ui_lang", "ru"),
                                       "history": case.get("history", []),
                                       "deal": case.get("deal") or {}},
                        ), ASSIST_TIMEOUT_S))
                        record["retrieve"] = retrieve
                        record["assist"] = assist
                        record["retrieve_ms"] = (time.monotonic() - started) * 1000
                        expect = dict(case.get("expect") or {})
                        checks, metrics = evaluate_expectations(
                            expect, retrieve, assist, case.get("ui_lang", "ru")
                        )
                        record["checks"] = checks
                        record["metrics"] = metrics
                        record["verdict"] = "PASS" if all(c["ok"] for c in checks) else "FAIL"
                    except Exception as exc:  # keep going: one bad case must not kill the run
                        record["error"] = f"{type(exc).__name__}: {exc}"
                        record["checks"] = []
                        record["metrics"] = {}
                        record["verdict"] = "ERROR"
                    record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
                    results.append(record)
                    jsonl.write(json.dumps(record, ensure_ascii=False) + "\n")
                    jsonl.flush()
                    failed = [c["name"] for c in record["checks"] if not c["ok"]]
                    note = record.get("error") or ("; ".join(failed) if failed else "")
                    print(f"[{i}/{len(cases)}] {record['verdict']:<5} {case['id']:<40} "
                          f"{record['elapsed_ms'] / 1000:5.1f}s"
                          + (f"  ← {note}" if note else ""))

    models = sorted({r["assist"]["validation"]["model"] for r in results
                     if r.get("assist") and r["assist"]["validation"]["model"]})
    thresholds = sorted({r["retrieve"]["threshold"] for r in results if r.get("retrieve")})
    n_pass = sum(1 for r in results if r["verdict"] == "PASS")
    ids1 = [r for r in results if r["metrics"].get("hit_at_1") is not None]
    summary = {
        "timestamp": ts,
        "base_url": args.base_url,
        "cases_file": str(args.cases),
        "model": ", ".join(models) or "-",
        "threshold": thresholds[0] if thresholds else None,
        "total": len(results),
        "pass": n_pass,
        "fail": sum(1 for r in results if r["verdict"] == "FAIL"),
        "error": sum(1 for r in results if r["verdict"] == "ERROR"),
        "hit_at_1": sum(1 for r in ids1 if r["metrics"]["hit_at_1"]),
        "hit_at_3": sum(1 for r in results if any(c["name"].startswith("ids@3") and c["ok"]
                                                  for c in r["checks"])),
        "ids_cases": len(ids1),
        "failures": [
            {"id": r["id"], "verdict": r["verdict"],
             "failed": [c["name"] for c in r["checks"] if not c["ok"]],
             "error": r.get("error")}
            for r in results if r["verdict"] != "PASS"
        ],
    }
    config = {"timestamp": ts, "base_url": args.base_url,
              "cases_file": str(args.cases.relative_to(ROOT)),
              "model": summary["model"], "threshold": summary["threshold"]}
    report = build_report(config, results)
    report_path.write_text(report, encoding="utf-8")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(report, encoding="utf-8")

    print(f"\ntotal={summary['total']} pass={summary['pass']} fail={summary['fail']} "
          f"error={summary['error']} hit@1={summary['hit_at_1']}/{summary['ids_cases']} "
          f"hit@3={summary['hit_at_3']}/{summary['ids_cases']}")
    print(f"report: {report_path}")
    if args.md:
        print(f"report copy: {args.md}")
    return 0 if summary["fail"] == 0 and summary["error"] == 0 else 1


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()

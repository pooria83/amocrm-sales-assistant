#!/usr/bin/env python3
"""Playwright demo/e2e runner for the 4 seeded scenarios (CONTEXT §6/§19/§7).

Modes:
  --record  headed Chromium, 1920x1080 video, narration pauses (make demo)
  --test    headless, no pauses, same assertions, exit 1 on failure
            (make demo-test)

The assistant run is triggered automatically when a chat is opened
(useAssist fires on status=idle); no extra button is needed.
Everything shown is REAL: the script talks to the running app and asserts
the actual /api/assist JSON — no mocks, no hardcoded model output.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import Page, Response, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.fallback import no_match_reply  # noqa: E402

VIDEOS_DIR = Path(__file__).resolve().parent / "videos"

# ---- narration pauses (record mode only; skipped in --test) ----
PAUSE_INTRO_S = 2.0
PAUSE_ON_MATCHES_S = 2.5
PAUSE_ON_REPLY_S = 3.0
PAUSE_ON_HINTS_S = 3.0
PAUSE_BEFORE_CLICK_S = 0.5
PAUSE_AFTER_SEND_S = 1.5
PAUSE_AFTER_NOTE_S = 2.0

# ---- timeouts ----
ASSIST_TIMEOUT_MS = 90_000
UI_TIMEOUT_MS = 15_000

# ---- selectors (real data-testid values from frontend/src) ----
SEL_REPLY = '[data-testid="customer-reply"] textarea'
SEL_HINTS = "[data-testid='internal-hints']"
SEL_SEND = '[data-testid="send-to-chat"]'
SEL_ADD_NOTE = '[data-testid="add-note"]'
SEL_BUBBLE_MANAGER = "[data-testid='bubble-manager']"
SEL_INTERNAL_NOTE = "[data-testid='internal-note']"
SEL_KB_MATCHES = '[data-testid="kb-matches"]'
SEL_FALLBACK = '[data-testid="fallback-banner"]'
SEL_BANNER = SEL_FALLBACK

# Playwright videos do not show the mouse — inject a visible fake cursor.
FAKE_CURSOR_JS = """
(() => {
  const init = () => {
    if (document.getElementById('pw-fake-cursor')) return;
    const c = document.createElement('div');
    c.id = 'pw-fake-cursor';
    c.style.cssText = [
      'position:fixed', 'left:24px', 'top:24px', 'width:22px', 'height:22px',
      'border:3px solid #1f2933', 'border-radius:50%',
      'background:rgba(47,128,237,.35)',
      'box-shadow:0 0 0 2px rgba(255,255,255,.9)',
      'pointer-events:none', 'z-index:2147483647',
      'transform:translate(-50%,-50%)',
    ].join(';');
    document.body.appendChild(c);
    document.addEventListener('mousemove', (e) => {
      c.style.left = e.clientX + 'px';
      c.style.top = e.clientY + 'px';
    }, true);
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
"""


def check_health(base_url: str) -> dict[str, Any]:
    """Prerequisite: the app must be up and Ollama reachable. Never mock."""
    try:
        resp = httpx.get(f"{base_url}/api/health", timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"App unreachable at {base_url} ({exc}). "
            "start the app: make up; warm the model: make warmup"
        ) from exc
    if data.get("ollama") != "reachable":
        raise SystemExit(
            "Ollama is not reachable — the demo needs the real model. "
            "start the app: make up; warm the model: make warmup"
        )
    return data


def assist_matcher(expected_prefix: str | None):
    """Match OUR /api/assist call among all responses.

    For scenario 1 the first assist on a fresh page is ours (expected_prefix
    None); for the others we match the seeded customer message taken from the
    chat-list preview (prefix match survives visual line-clamping).
    """

    def match(response: Response) -> bool:
        if response.request.method != "POST" or not response.url.endswith("/api/assist"):
            return False
        if expected_prefix is None:
            return True
        try:
            payload = json.loads(response.request.post_data or "{}")
        except json.JSONDecodeError:
            return False
        message = str(payload.get("message", "")).strip()
        return bool(message) and message.startswith(expected_prefix)

    return match


@dataclass
class Runner:
    page: Page
    base_url: str
    record: bool
    t0: float
    timeline: list[dict[str, float | str]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    # ---- timing / narration ----
    def narration_pause(self, seconds: float) -> None:
        if self.record and seconds > 0:
            time.sleep(seconds)

    def begin_segment(self, name: str) -> dict[str, float | str]:
        return {"name": name, "start": round(time.monotonic() - self.t0, 3)}

    def end_segment(self, segment: dict[str, float | str]) -> None:
        segment["end"] = round(time.monotonic() - self.t0, 3)
        self.timeline.append(segment)

    # ---- cursor (record mode only; videos do not show the real mouse) ----
    def move_to(self, selector: str) -> None:
        if not self.record:
            return
        box = self.page.locator(selector).first.bounding_box()
        if box:
            self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=25)

    def click(self, selector: str) -> None:
        self.move_to(selector)
        self.narration_pause(PAUSE_BEFORE_CLICK_S)
        self.page.locator(selector).first.click()

    # ---- assertions ----
    def check(self, scenario: str, ok: bool, label: str) -> bool:
        print(f"[{'PASS' if ok else 'FAIL'}] {scenario}: {label}")
        if not ok:
            self.failures.append(f"{scenario}: {label}")
        return ok


def open_scenario(runner: Runner, n: int) -> dict[str, Any]:
    """Select scenario n in the chat list and capture its real /api/assist JSON."""
    key = f"s{n}"
    preview = runner.page.locator(f'[data-testid="chat-item-{key}"] p').inner_text()
    prefix = " ".join(preview.split()).rstrip("…").strip()
    with runner.page.expect_response(assist_matcher(prefix), timeout=ASSIST_TIMEOUT_MS) as info:
        runner.click(f'[data-testid="chat-item-{key}"]')
    response = info.value
    if response.status != 200:
        raise RuntimeError(f"/api/assist returned HTTP {response.status}")
    return response.json()


def wait_for_results(page: Page) -> None:
    """Results are ready when the internal-hints card renders (status=done)."""
    page.wait_for_selector(SEL_HINTS, state="visible", timeout=ASSIST_TIMEOUT_MS)


def reply_ui(page: Page) -> str:
    return page.input_value(SEL_REPLY).strip()


def hint_strings(assist: dict[str, Any]) -> list[str]:
    hints = assist["internal_sales_hints"]
    out: list[str] = []
    for item in [*hints["upsell"], *hints["cross_sell"]]:
        out.extend([item["reason"], item["talking_point"], item["title"]])
    if hints.get("notes"):
        out.append(hints["notes"])
    return [s for s in out if s]


def leakage_texts(assist: dict[str, Any], texts: list[str]) -> list[str]:
    """Return a list of leakage violations across the given customer-visible texts.

    Mirrors the backend no_leakage contract (CONTEXT §17): internal reason /
    talking_point text, candidate/match ids and marker words. Hint *titles* are
    product names and may legitimately answer a customer question (spec S3
    requires naming «Advanced Analytics» in the reply), so they are not banned.
    """
    hints = assist["internal_sales_hints"]
    internal = []
    for item in [*hints["upsell"], *hints["cross_sell"]]:
        internal.extend([item["reason"], item["talking_point"]])
    if hints.get("notes"):
        internal.append(hints["notes"])
    internal = [s for s in internal if len(s) >= 8]
    banned_ids = {item["id"] for item in [*hints["upsell"], *hints["cross_sell"]]}
    banned_ids |= {m["id"] for m in assist["retrieval"]["matches"]}
    banned_words = ("допродаж", "upsell", "cross-sell")
    violations: list[str] = []
    for text in texts:
        low = text.lower()
        for snippet in internal:
            if snippet.lower() in low:
                violations.append(f"internal hint text leaked: {snippet[:60]!r}")
        for kb_id in sorted(banned_ids):
            if kb_id.lower() in low:
                violations.append(f"candidate id leaked: {kb_id}")
        for word in banned_words:
            if word in low:
                violations.append(f"banned word leaked: {word}")
    return violations


def check_common(runner: Runner, scenario: str, assist: dict[str, Any]) -> str:
    """Checks shared by all scenarios; returns the reply text."""
    validation = assist["validation"]
    runner.check(scenario, validation["schema_ok"] is True, "validation.schema_ok")
    runner.check(scenario, validation["language_ok"] is True, "validation.language_ok")
    runner.check(scenario, validation["no_leakage"] is True, "validation.no_leakage")
    reply = assist["customer_reply"]["text"]
    runner.check(scenario, reply_ui(runner.page) == reply.strip(), "UI reply equals API reply")
    return reply


def assert_s1(runner: Runner, scenario: str, assist: dict[str, Any]) -> None:
    reply = check_common(runner, scenario, assist)
    ids = [m["id"] for m in assist["retrieval"]["matches"]]
    runner.check(scenario, "plan-start" in ids, f"match plan-start present ({ids})")
    runner.check(scenario, "int-telegram" in ids, f"match int-telegram present ({ids})")
    runner.check(scenario, "5" in reply, 'reply mentions the seat limit "5"')
    upsell_ids = [h["id"] for h in assist["internal_sales_hints"]["upsell"]]
    runner.check(scenario, "plan-business" in upsell_ids, f"upsell plan-business ({upsell_ids})")
    runner.check(scenario, assist["validation"]["numbers_ok"] is True, "validation.numbers_ok")


def assert_s2(runner: Runner, scenario: str, assist: dict[str, Any]) -> None:
    reply = check_common(runner, scenario, assist)
    runner.check(scenario, "20%" in reply, 'reply contains the KB discount "20%"')
    cross_ids = [h["id"] for h in assist["internal_sales_hints"]["cross_sell"]]
    runner.check(scenario, "addon-onboarding" in cross_ids, f"cross-sell addon-onboarding ({cross_ids})")
    percentages = set(re.findall(r"(\d+)\s*%", reply))
    runner.check(scenario, percentages == {"20"}, f"only 20% appears in the reply (found {percentages})")


def assert_s3(runner: Runner, scenario: str, assist: dict[str, Any]) -> None:
    reply = check_common(runner, scenario, assist)
    runner.check(scenario, assist["detected_lang"] == "en", "detected_lang == en")
    has_cyrillic = re.search(r"[\u0400-\u04FF]", reply) is not None
    runner.check(scenario, not has_cyrillic, "customer reply has no Cyrillic")
    hints_text = " ".join(hint_strings(assist))
    runner.check(
        scenario,
        re.search(r"[\u0400-\u04FF]", hints_text) is not None,
        "internal hints have Cyrillic (manager UI language)",
    )
    cross_ids = [h["id"] for h in assist["internal_sales_hints"]["cross_sell"]]
    runner.check(scenario, "addon-analytics" in cross_ids, f"cross-sell addon-analytics ({cross_ids})")


def assert_s4(runner: Runner, scenario: str, assist: dict[str, Any]) -> None:
    reply = check_common(runner, scenario, assist)
    runner.check(scenario, assist["grounded"] is False, "grounded == false")
    runner.check(scenario, assist["validation"]["fallback_used"] is True, "validation.fallback_used")
    hints = assist["internal_sales_hints"]
    runner.check(scenario, hints["upsell"] == [], "upsell empty")
    runner.check(scenario, hints["cross_sell"] == [], "cross-sell empty")
    runner.check(scenario, runner.page.locator(SEL_FALLBACK).is_visible(), "fallback banner visible")
    expected = no_match_reply("ru", "Сергей")
    runner.check(scenario, reply == expected.strip(), "reply is the templated RU fallback")


def narration_and_actions(runner: Runner, scenario: str, assist: dict[str, Any]) -> None:
    """Narration pauses on the three result blocks, then send + note clicks."""
    if runner.page.locator(SEL_KB_MATCHES).count() > 0:
        runner.move_to(SEL_KB_MATCHES)
        runner.narration_pause(PAUSE_ON_MATCHES_S)
    runner.move_to('[data-testid="customer-reply"]')
    runner.narration_pause(PAUSE_ON_REPLY_S)
    runner.move_to(SEL_HINTS)
    runner.narration_pause(PAUSE_ON_HINTS_S)

    # «Отправить в чат» → the reply appears as an outgoing bubble
    bubbles_before = runner.page.locator(SEL_BUBBLE_MANAGER).count()
    runner.click(SEL_SEND)
    runner.page.wait_for_function(
        "([sel, n]) => document.querySelectorAll(sel).length > n",
        arg=[SEL_BUBBLE_MANAGER, bubbles_before],
        timeout=UI_TIMEOUT_MS,
    )
    bubble = runner.page.locator(SEL_BUBBLE_MANAGER).last.inner_text().strip()
    runner.check(scenario, bubble == reply_ui(runner.page), "outgoing bubble equals the reply")
    runner.narration_pause(PAUSE_AFTER_SEND_S)

    # «Добавить примечание» → yellow internal note, never a chat bubble
    notes_before = runner.page.locator(SEL_INTERNAL_NOTE).count()
    bubbles_still = runner.page.locator(SEL_BUBBLE_MANAGER).count()
    runner.click(SEL_ADD_NOTE)
    runner.page.wait_for_function(
        "([sel, n]) => document.querySelectorAll(sel).length > n",
        arg=[SEL_INTERNAL_NOTE, notes_before],
        timeout=UI_TIMEOUT_MS,
    )
    runner.check(
        scenario,
        runner.page.locator(SEL_BUBBLE_MANAGER).count() == bubbles_still,
        "note did not become a chat bubble",
    )
    runner.narration_pause(PAUSE_AFTER_NOTE_S)


ASSERTS = {1: assert_s1, 2: assert_s2, 3: assert_s3, 4: assert_s4}


def run_scenario(runner: Runner, n: int, preloaded: dict[str, Any] | None) -> None:
    scenario = f"S{n}"
    failures_before = len(runner.failures)
    try:
        assist = preloaded if preloaded is not None else open_scenario(runner, n)
        wait_for_results(runner.page)
        ASSERTS[n](runner, scenario, assist)
        narration_and_actions(runner, scenario, assist)
        reply = reply_ui(runner.page)
        bubble = runner.page.locator(SEL_BUBBLE_MANAGER).last.inner_text().strip()
        for violation in leakage_texts(assist, [reply, bubble]):
            runner.check(scenario, False, f"leakage: {violation}")
    except Exception as exc:  # noqa: BLE001
        runner.check(scenario, False, f"exception: {type(exc).__name__}: {exc}")
    if len(runner.failures) > failures_before:
        shot = VIDEOS_DIR / f"fail-{scenario.lower()}.png"
        try:
            runner.page.screenshot(path=str(shot))
            print(f"[screenshot] {shot}")
        except Exception as exc:  # noqa: BLE001
            print(f"[screenshot failed] {exc}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--record", action="store_true", help="headed + video + narration pauses")
    mode.add_argument("--test", action="store_true", help="headless, no pauses, exit 1 on failure")
    parser.add_argument("--scenario", type=int, choices=[1, 2, 3, 4], help="run one scenario")
    parser.add_argument("--base-url", default="http://localhost:8000")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    check_health(args.base_url)
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    record = not args.test
    scenario_nums = [args.scenario] if args.scenario else [1, 2, 3, 4]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=args.test)
        context_kwargs: dict[str, Any] = {"viewport": {"width": 1920, "height": 1080}}
        if record:
            context_kwargs["record_video_dir"] = str(VIDEOS_DIR)
            context_kwargs["record_video_size"] = {"width": 1920, "height": 1080}
        context = browser.new_context(**context_kwargs)
        if record:
            context.add_init_script(FAKE_CURSOR_JS)
        page = context.new_page()
        video = page.video if record else None
        runner = Runner(page=page, base_url=args.base_url, record=record, t0=time.monotonic())

        intro: dict[str, float | str] | None = runner.begin_segment("intro") if record else None
        preloaded: dict[str, Any] | None = None
        if 1 in scenario_nums:
            with page.expect_response(assist_matcher(None), timeout=ASSIST_TIMEOUT_MS) as info:
                page.goto(args.base_url, wait_until="load")
            if info.value.status != 200:
                print(f"[WARN] initial /api/assist HTTP {info.value.status}")
            preloaded = info.value.json()
        else:
            page.goto(args.base_url, wait_until="load")
        if record:
            page.mouse.move(960, 540, steps=8)
        if preloaded is not None:
            wait_for_results(page)
            runner.narration_pause(PAUSE_INTRO_S)
        elif record:
            runner.narration_pause(PAUSE_INTRO_S)
        if intro is not None:
            runner.end_segment(intro)

        for n in scenario_nums:
            segment = runner.begin_segment(f"s{n}") if record else None
            run_scenario(runner, n, preloaded if n == 1 else None)
            preloaded = None
            if segment is not None:
                runner.end_segment(segment)

        timeline_path = VIDEOS_DIR / "timeline.json"
        video_path: str | None = None
        if record:
            timeline_path.write_text(
                json.dumps({"segments": runner.timeline}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        # Close the context first so the .webm is flushed, then resolve its path.
        context.close()
        if video is not None:
            video_path = video.path()
        browser.close()

    print()
    if runner.failures:
        print(f"FAILURES ({len(runner.failures)}):")
        for failure in runner.failures:
            print(f"  - {failure}")
    else:
        print("ALL ASSERTIONS PASSED")
    if record:
        print(f"Timeline: {timeline_path}")
        if video_path:
            print(f"Video: {video_path}")
    return 1 if runner.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

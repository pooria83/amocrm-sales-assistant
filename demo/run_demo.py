#!/usr/bin/env python3
"""Playwright demo/e2e runner for the 4 seeded scenarios (CONTEXT §6/§19/§7).

Modes:
  --record  headed Chromium, 1920x1080 video, narration pauses (make demo)
  --test    headless, no pauses, same assertions, exit 1 on failure
            (make demo-test)
  --takes N independent recorded takes per scenario with marks + validity
            (video pipeline, VIDEO_PROMPT §7)

The assistant run is triggered automatically when a chat is opened
(useAssist fires on status=idle); no extra button is needed.
Everything shown is REAL: the script talks to the running app and asserts
the actual /api/assist JSON — no mocks, no hardcoded model output.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
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

# ---- per-scenario presentation dwell (record-only pacing for narration fit) ----
# each entry: pulse seconds + sleep seconds per highlight block, think-pause before
# «Отправить в чат», and the hold after «Добавить примечание» (spec >= 1.5 s).
DWELL: dict[int, dict[str, object]] = {
    1: {"bubble": (0.9, 2.6), "kb": (1.1, 2.2), "chips": (0.6, 0.8), "badges": (0.6, 0.8),
        "reply": (0.9, 2.2), "hints": (0.9, 2.2), "presend": 1.6, "after_note": 2.2},
    2: {"bubble": (0.8, 1.4), "kb": (1.0, 1.0), "chips": (0.6, 0.4), "badges": (0.6, 0.4),
        "reply": (0.8, 1.0), "hints": (0.8, 1.0), "presend": 0.5, "after_note": 1.5},
    3: {"bubble": (0.8, 1.3), "kb": (0.9, 1.1), "chips": (0.5, 0.4), "badges": (0.5, 0.4),
        "reply": (0.8, 1.2), "hints": (0.8, 1.2), "presend": 0.5, "after_note": 1.5},
    4: {"bubble": (0.8, 1.3), "kb": (0.0, 0.0), "chips": (0.0, 0.0), "badges": (0.5, 0.5),
        "fb": (1.0, 1.2), "reply": (0.8, 1.1), "hints": (0.8, 1.1), "presend": 0.5,
        "after_note": 1.5},
}

# ---- timeouts ----
ASSIST_TIMEOUT_MS = 130_000
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



# ==================== video takes mode (VIDEO_PROMPT §7) ====================

TAKES_DIR = VIDEOS_DIR / "takes"

# Record-only visual effects injected at runtime (add_init_script) — never part
# of the app source. Eased fake cursor, click ripple, element highlight rings.
FX_INIT_JS = r"""
(() => {
  let cur = null, raf = null;
  const pos = {x: 40, y: 40};
  const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  function ensureCursor() {
    if (cur && cur.isConnected) return cur;
    cur = document.createElement('div');
    cur.setAttribute('data-fx', 'cursor');
    cur.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;pointer-events:none;' +
      'z-index:2147483647;will-change:transform;filter:drop-shadow(0 1px 2px rgba(0,0,0,.45));';
    cur.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24">' +
      '<path d="M5 2 L5 19 L9.5 14.8 L12.4 21.4 L15.4 20 L12.5 13.6 L18.6 13.6 Z" ' +
      'fill="#1f2937" stroke="#ffffff" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    (document.body || document.documentElement).appendChild(cur);
    render();
    return cur;
  }
  function render() { if (cur) cur.style.transform = 'translate(' + pos.x + 'px,' + pos.y + 'px)'; }
  function moveTo(x, y, dur) {
    ensureCursor();
    if (raf) cancelAnimationFrame(raf);
    const sx = pos.x, sy = pos.y, t0 = performance.now();
    dur = dur || 340;
    return new Promise((resolve) => {
      const step = (now) => {
        const k = Math.min(1, (now - t0) / dur), e = ease(k);
        pos.x = sx + (x - sx) * e; pos.y = sy + (y - sy) * e; render();
        if (k < 1) raf = requestAnimationFrame(step); else { raf = null; resolve([x, y]); }
      };
      raf = requestAnimationFrame(step);
    });
  }
  function cursorTo(testid, dur) {
    const el = document.querySelector('[data-testid="' + testid + '"]');
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
    moveTo(cx, cy, dur || 340);
    return [cx, cy];
  }
  function ripple(cx, cy) {
    const d = document.createElement('div');
    d.style.cssText = 'position:fixed;left:' + (cx - 20) + 'px;top:' + (cy - 20) + 'px;width:40px;height:40px;' +
      'border-radius:50%;border:3px solid rgba(43,110,255,.9);pointer-events:none;z-index:2147483647;';
    document.body.appendChild(d);
    const a = d.animate(
      [{transform: 'scale(.3)', opacity: .95}, {transform: 'scale(2.1)', opacity: 0}],
      {duration: 540, easing: 'cubic-bezier(.2,.7,.3,1)'}
    );
    a.onfinish = () => d.remove();
  }
  function pulse(testid, ms, pickLast) {
    const els = document.querySelectorAll('[data-testid="' + testid + '"]');
    if (!els.length) return false;
    const el = pickLast ? els[els.length - 1] : els[0];
    const visible = () => {
      if (el.checkVisibility && !el.checkVisibility({checkVisibilityCSS: true})) return false;
      const r = el.getBoundingClientRect();
      if (r.width < 8 || r.height < 8) return false;
      if (r.bottom < 48 || r.top > innerHeight - 48) return false;
      if (r.right < 48 || r.left > innerWidth - 48) return false;
      return true;
    };
    if (!visible()) return false;
    const pad = 6;
    const ring = document.createElement('div');
    ring.style.cssText = 'position:fixed;pointer-events:none;z-index:2147483646;' +
      'border:3px solid rgba(43,110,255,.95);border-radius:10px;' +
      'box-shadow:0 0 0 4px rgba(43,110,255,.16),0 6px 22px rgba(43,110,255,.30);';
    document.body.appendChild(ring);
    const t0 = performance.now();
    const step = (now) => {
      const p = (now - t0) / ms;
      if (p >= 1 || !visible()) { ring.remove(); return; }
      const r = el.getBoundingClientRect();
      ring.style.left = (r.x - pad) + 'px';
      ring.style.top = (r.y - pad) + 'px';
      ring.style.width = (r.width + 2 * pad) + 'px';
      ring.style.height = (r.height + 2 * pad) + 'px';
      ring.style.opacity = p < 0.16 ? (p / 0.16) : (p > 0.74 ? (1 - (p - 0.74) / 0.26) : 1);
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
    return true;
  }
  window.__fx = {moveTo, cursorTo, ripple, pulse, pos};
})();
"""

TAKE_MARKS_REQUIRED = (
    "scenario_start",
    "customer_message_visible",
    "retrieve_start",
    "retrieve_done",
    "llm_start",
    "llm_done",
    "reply_visible",
    "internal_hint_visible",
    "send_clicked",
    "reply_sent",
    "note_clicked",
    "note_added",
    "scenario_end",
)

VALIDATION_FLAGS = ("schema_ok", "language_ok", "numbers_ok", "no_leakage")


@dataclass
class TakeOutcome:
    scenario: str  # "intro" | "s1" .. "s4"
    take: int
    valid: bool
    reasons: list[str]
    latency_s: float
    visual_s: float
    video: str | None
    marks_path: str | None
    assist_path: str | None


@dataclass
class TakeRunner(Runner):
    """Runner extended with page-origin marks and record-only FX helpers."""

    marks: dict[str, float] = field(default_factory=dict)
    in_view: dict[str, bool] = field(default_factory=dict)
    latency_s: float = 0.0

    # ---- marks (page-origin seconds, VIDEO_PROMPT §9) ----
    def mark(self, name: str) -> None:
        self.marks[name] = round(time.monotonic() - self.t0, 3)

    # ---- record-only visual effects ----
    def fx_pulse(self, testid: str, ms: int = 1200, last: bool = False) -> bool:
        if not self.record:
            return False
        return bool(
            self.page.evaluate(
                "([id, ms, last]) => window.__fx ? window.__fx.pulse(id, ms, last) : false",
                [testid, ms, last],
            )
        )

    def fx_cursor_to(self, testid: str, dur: int = 340) -> list[float] | None:
        if not self.record:
            return None
        return self.page.evaluate(
            "([id, dur]) => window.__fx ? window.__fx.cursorTo(id, dur) : null", [testid, dur]
        )

    def fx_click(self, testid: str, dur: int = 340) -> None:
        """Eased cursor → pre-click pause → ripple → real click."""
        center = self.fx_cursor_to(testid, dur) if self.record else None
        if center is not None:
            time.sleep(dur / 1000 + 0.18)
            self.page.evaluate("([x, y]) => window.__fx && window.__fx.ripple(x, y)", center)
        else:
            self.move_to(f'[data-testid="{testid}"]')
            self.narration_pause(PAUSE_BEFORE_CLICK_S)
        self.page.locator(f'[data-testid="{testid}"]').first.click()

    def camera_center(self, testids: list[str], settle: float = 0.55) -> None:
        """Smoothly scroll the shared scrollable ancestor so all cards fit in view."""
        if not self.record:
            return
        js = """
(ids) => {
  const els = ids.map(id => document.querySelector('[data-testid="' + id + '"]')).filter(Boolean);
  if (!els.length) return false;
  const rects = els.map(el => el.getBoundingClientRect());
  let anc = els[0].parentElement, sc = null;
  while (anc) {
    const cs = getComputedStyle(anc);
    if ((cs.overflowY === 'auto' || cs.overflowY === 'scroll') && anc.scrollHeight > anc.clientHeight) { sc = anc; break; }
    anc = anc.parentElement;
  }
  const uTop = Math.min(...rects.map(r => r.top));
  const uBot = Math.max(...rects.map(r => r.bottom));
  if (sc) {
    const sr = sc.getBoundingClientRect();
    let delta = 0;
    if (uBot > sr.bottom - 8) delta = uBot - (sr.bottom - 8);
    else if (uTop < sr.top + 8) delta = uTop - (sr.top + 8);
    if (delta) { sc.scrollTo({top: sc.scrollTop + delta, behavior: 'smooth'}); return true; }
    return false;
  }
  els[0].scrollIntoView({behavior: 'smooth', block: 'center'});
  return true;
}
"""
        self.page.evaluate(js, testids)
        time.sleep(settle)

    def rect_in_view(self, testid: str) -> bool:
        return bool(
            self.page.evaluate(
                """
(id) => {
  const el = document.querySelector('[data-testid="' + id + '"]');
  if (!el) return false;
  const r = el.getBoundingClientRect();
  return r.top >= 0 && r.left >= 0 && r.bottom <= innerHeight && r.right <= innerWidth;
}
""",
                testid,
            )
        )


def warmup_ollama() -> None:
    """Keep the video model resident before recording (VIDEO_PROMPT §7)."""
    import urllib.request

    base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.environ.get("LLM_MODEL", "qwen2.5:7b")
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "привет"}],
            "stream": False,
            "keep_alive": "30m",
            "options": {"temperature": 0.0},
        }
    ).encode()
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(f"{base}/api/chat", data=payload, timeout=120) as resp:
            resp.read()
        print(f"[warmup] {model} ready in {time.monotonic() - t0:.1f}s")
    except Exception as exc:  # noqa: BLE001
        print(f"[warmup] WARN: {type(exc).__name__}: {exc}")


def attach_mark_listeners(runner: TakeRunner, page: Page, target_prefix: str | None) -> None:
    """Record retrieve/llm timestamps in page-origin seconds at event time.

    target_prefix None ⇒ the first retrieve/assist call on a fresh page is the
    target (scenario 1 opens on load); otherwise only requests whose payload
    message starts with the chat-preview prefix are marked (scenarios 2–4).
    """
    state = {
        "retrieve_started": False, "retrieve_done": False,
        "assist_started": False, "assist_done": False,
    }

    def _match(kind: str, url: str, post_data: str | None) -> bool:
        if not url.endswith(f"/api/{kind}"):
            return False
        try:
            payload = json.loads(post_data or "{}")
        except json.JSONDecodeError:
            return False
        msg = str(payload.get("message", "")).strip()
        if not msg:
            return False
        if target_prefix is None:
            return True
        return msg.startswith(target_prefix)

    def on_request(request) -> None:  # noqa: ANN001
        if request.method != "POST":
            return
        if _match("retrieve", request.url, request.post_data):
            if not state["retrieve_started"]:
                state["retrieve_started"] = True
                runner.mark("retrieve_start")
        elif _match("assist", request.url, request.post_data):
            if not state["assist_started"]:
                state["assist_started"] = True
                runner.mark("llm_start")

    def on_response(response) -> None:  # noqa: ANN001
        if response.request.method != "POST":
            return
        if _match("retrieve", response.url, response.request.post_data):
            if state["retrieve_started"] and not state["retrieve_done"]:
                state["retrieve_done"] = True
                runner.mark("retrieve_done")
        elif _match("assist", response.url, response.request.post_data):
            if state["assist_started"] and not state["assist_done"]:
                state["assist_done"] = True
                runner.mark("llm_done")
                start = runner.marks.get("llm_start")
                if start is not None:
                    runner.latency_s = round(runner.marks["llm_done"] - start, 3)

    page.on("request", on_request)
    page.on("response", on_response)


def _new_take_context(browser, tmp_dir: Path):  # noqa: ANN202
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        record_video_dir=str(tmp_dir),
        record_video_size={"width": 1920, "height": 1080},
    )
    context.add_init_script(FX_INIT_JS)
    return context


def _finalize_take(  # noqa: PLR0913
    scenario: str,
    take_idx: int,
    context,  # noqa: ANN001
    tmp_dir: Path,
    runner: TakeRunner,
    reasons: list[str],
    assist: dict[str, Any] | None,
) -> TakeOutcome:
    context.close()
    video_path: str | None = None
    videos = sorted(tmp_dir.glob("*.webm"))
    if videos:
        dest = TAKES_DIR / f"{scenario}_take{take_idx}.webm"
        shutil.move(str(videos[0]), str(dest))
        video_path = str(dest)
    shutil.rmtree(tmp_dir, ignore_errors=True)

    marks_path: str | None = None
    assist_path: str | None = None
    marks_doc = {
        "scenario": scenario,
        "take": take_idx,
        "origin": "page-creation",
        "marks": runner.marks,
        "in_view": runner.in_view,
        "latency_s": runner.latency_s,
        "visual_s": round(
            runner.marks.get("scenario_end", 0.0) - runner.marks.get("scenario_start", 0.0), 3
        ),
        "failures": reasons,
        "valid": not reasons,
    }
    marks_file = TAKES_DIR / f"{scenario}_take{take_idx}.marks.json"
    marks_file.write_text(json.dumps(marks_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    marks_path = str(marks_file)
    if assist is not None:
        assist_file = TAKES_DIR / f"{scenario}_take{take_idx}.assist.json"
        assist_file.write_text(json.dumps(assist, ensure_ascii=False, indent=2), encoding="utf-8")
        assist_path = str(assist_file)

    outcome = TakeOutcome(
        scenario=scenario,
        take=take_idx,
        valid=not reasons,
        reasons=reasons,
        latency_s=runner.latency_s,
        visual_s=marks_doc["visual_s"],
        video=video_path,
        marks_path=marks_path,
        assist_path=assist_path,
    )
    status = "ACCEPT" if outcome.valid else "REJECT"
    print(
        f"[{status}] {scenario} take{take_idx} "
        f"latency={outcome.latency_s:.1f}s visual={outcome.visual_s:.1f}s"
        + (f" :: {'; '.join(reasons)}" if reasons else "")
    )
    return outcome


def run_scenario_take(browser, n: int, take_idx: int, base_url: str) -> TakeOutcome:  # noqa: ANN001
    """One independent take of scenario n: fresh context, marks, choreography."""
    scenario = f"s{n}"
    tmp_dir = TAKES_DIR / f"_tmp_{scenario}_take{take_idx}"
    context = _new_take_context(browser, tmp_dir)
    page = context.new_page()
    runner = TakeRunner(page=page, base_url=base_url, record=True, t0=time.monotonic())
    assist: dict[str, Any] | None = None

    try:
        prefix: str | None = None
        if n > 1:
            page.goto(base_url, wait_until="load")
            page.wait_for_selector('[data-testid="chat-list"]', state="visible", timeout=UI_TIMEOUT_MS)
            key = f"s{n}"
            preview = page.locator(f'[data-testid="chat-item-{key}"] p').inner_text()
            prefix = " ".join(preview.split()).rstrip("…").strip()
        attach_mark_listeners(runner, page, prefix)

        # Non-blocking response capture: the customer bubble is marked BEFORE the
        # LLM answers, so the mark reflects when the message actually appeared.
        matcher = assist_matcher(prefix)
        resp_box: dict[str, Any] = {}

        def _grab(resp: Response) -> None:
            if "resp" not in resp_box and matcher(resp):
                resp_box["resp"] = resp

        page.on("response", _grab)
        runner.mark("scenario_start")
        if n == 1:
            page.goto(base_url, wait_until="load")
        else:
            runner.fx_click(f"chat-item-s{n}")

        page.wait_for_function(
            """([prefix]) => {
                const els = document.querySelectorAll('[data-testid="bubble-customer"]');
                if (!els.length) return false;
                const txt = (els[els.length - 1].innerText || '').replace(/\\s+/g, ' ').trim();
                return prefix ? txt.startsWith(prefix) : true;
            }""",
            arg=[prefix or ""],
            timeout=UI_TIMEOUT_MS,
        )
        runner.mark("customer_message_visible")

        deadline = time.monotonic() + ASSIST_TIMEOUT_MS / 1000
        while "resp" not in resp_box and time.monotonic() < deadline:
            # page.evaluate pumps the sync-API event loop: without it, the
            # captured response event stays queued until context.close().
            page.evaluate("() => 0")
            time.sleep(0.05)
        if "resp" not in resp_box:
            raise TimeoutError("/api/assist response not captured")
        resp = resp_box["resp"]
        if resp.status != 200:
            raise RuntimeError(f"/api/assist returned HTTP {resp.status}")
        assist = resp.json()

        # --- choreography (record-only; highlight order per VIDEO_PROMPT §8) ---
        d = DWELL[n]
        pb, sb = d["bubble"]
        runner.fx_pulse("bubble-customer", int(pb * 1000), last=True)
        time.sleep(sb)

        if n == 4:
            pb, sb = d["badges"]
            if pb > 0:
                runner.fx_pulse("assistant-badges", int(pb * 1000))
                time.sleep(sb)
            page.wait_for_selector(SEL_FALLBACK, state="visible", timeout=ASSIST_TIMEOUT_MS)
            runner.mark("fallback_visible")
            pf, sf = d["fb"]
            runner.fx_pulse("fallback-banner", int(pf * 1000))
            time.sleep(sf)
        else:
            try:
                page.wait_for_selector(SEL_KB_MATCHES, state="visible", timeout=6000)
                for testid, key2 in (("kb-matches", "kb"), ("source-chips", "chips"), ("assistant-badges", "badges")):
                    pk, sk = d[key2]
                    if pk > 0:
                        runner.fx_pulse(testid, int(pk * 1000))
                        time.sleep(sk)
            except Exception:  # noqa: BLE001  # no matches above the threshold
                pass

        wait_for_results(page)
        page.wait_for_function(
            "sel => { const el = document.querySelector(sel); return el && el.value.trim().length > 0; }",
            arg=SEL_REPLY,
            timeout=UI_TIMEOUT_MS,
        )
        runner.mark("reply_visible")
        runner.mark("internal_hint_visible")
        runner.camera_center(["customer-reply", "internal-hints"])
        runner.in_view["customer-reply"] = runner.rect_in_view("customer-reply")
        runner.in_view["internal-hints"] = runner.rect_in_view("internal-hints")
        runner.in_view["deal-card"] = runner.rect_in_view("deal-card")
        pr, sr = d["reply"]
        runner.fx_pulse("customer-reply", int(pr * 1000))
        time.sleep(sr)
        ph, sh = d["hints"]
        runner.fx_pulse("internal-hints", int(ph * 1000))
        time.sleep(sh)

        ASSERTS[n](runner, scenario, assist)

        # --- «Отправить в чат» → outgoing bubble ---
        time.sleep(float(d["presend"]))
        bubbles_before = page.locator(SEL_BUBBLE_MANAGER).count()
        runner.fx_click("send-to-chat")
        runner.mark("send_clicked")
        page.wait_for_function(
            "([sel, n]) => document.querySelectorAll(sel).length > n",
            arg=[SEL_BUBBLE_MANAGER, bubbles_before],
            timeout=UI_TIMEOUT_MS,
        )
        runner.mark("reply_sent")
        bubble = page.locator(SEL_BUBBLE_MANAGER).last.inner_text().strip()
        runner.check(scenario, bubble == reply_ui(page), "outgoing bubble equals the reply")
        runner.fx_pulse("bubble-manager", 900, last=True)
        time.sleep(PAUSE_AFTER_SEND_S)

        # --- «Добавить примечание» → yellow internal note ---
        notes_before = page.locator(SEL_INTERNAL_NOTE).count()
        bubbles_still = page.locator(SEL_BUBBLE_MANAGER).count()
        runner.fx_click("add-note")
        runner.mark("note_clicked")
        page.wait_for_function(
            "([sel, n]) => document.querySelectorAll(sel).length > n",
            arg=[SEL_INTERNAL_NOTE, notes_before],
            timeout=UI_TIMEOUT_MS,
        )
        runner.mark("note_added")
        runner.check(
            scenario,
            page.locator(SEL_BUBBLE_MANAGER).count() == bubbles_still,
            "note did not become a chat bubble",
        )
        runner.fx_pulse("internal-note", 1100)
        time.sleep(float(d["after_note"]))

        # --- leakage on every customer-visible text ---
        reply = reply_ui(page)
        bubble = page.locator(SEL_BUBBLE_MANAGER).last.inner_text().strip()
        for violation in leakage_texts(assist, [reply, bubble]):
            runner.check(scenario, False, f"leakage: {violation}")
        runner.mark("scenario_end")

    except Exception as exc:  # noqa: BLE001
        runner.check(scenario, False, f"exception: {type(exc).__name__}: {exc}")

    # ---- validity (VIDEO_PROMPT §7 retake rules) ----
    reasons = list(runner.failures)
    missing = [m for m in TAKE_MARKS_REQUIRED if m not in runner.marks]
    if n == 4 and "fallback_visible" not in runner.marks:
        missing.append("fallback_visible")
    if missing:
        reasons.append(f"missing marks: {missing}")
    if runner.in_view and not all(runner.in_view.values()):
        reasons.append(f"cards not fully in view: {runner.in_view}")
    if assist is None:
        reasons.append("no assist response captured")
    else:
        validation = assist["validation"]
        if n == 4:
            if validation.get("fallback_used") is not True:
                reasons.append("fallback expected but fallback_used != true")
        else:
            if validation.get("fallback_used") is True:
                reasons.append("fallback_used true (unexpected)")
            for flag in VALIDATION_FLAGS:
                if validation.get(flag) is not True:
                    reasons.append(f"validation.{flag} != true")
            if runner.latency_s > 30:
                reasons.append(f"latency {runner.latency_s:.1f}s > 30s")
    if reasons:
        try:
            page.screenshot(path=str(TAKES_DIR / f"fail-{scenario}_take{take_idx}.png"))
        except Exception:  # noqa: BLE001
            pass

    return _finalize_take(scenario, take_idx, context, tmp_dir, runner, reasons, assist)


def run_intro_take(browser, take_idx: int, base_url: str) -> TakeOutcome:  # noqa: ANN001
    """~6 s establishing shot: chat list with unread badges (VIDEO_PROMPT §7.1)."""
    scenario = "intro"
    tmp_dir = TAKES_DIR / f"_tmp_{scenario}_take{take_idx}"
    context = _new_take_context(browser, tmp_dir)
    page = context.new_page()
    runner = TakeRunner(page=page, base_url=base_url, record=True, t0=time.monotonic())
    try:
        runner.mark("scenario_start")
        page.goto(base_url, wait_until="load")
        page.wait_for_selector('[data-testid="chat-list"]', state="visible", timeout=UI_TIMEOUT_MS)
        runner.check("intro", page.locator('[data-testid="chat-list"]').count() > 0, "chat list visible")
        for i, key in enumerate(["s1", "s2", "s3", "s4"]):
            runner.fx_cursor_to(f"chat-item-{key}", 420)
            time.sleep(0.45)
            if i in (1, 2):
                runner.fx_pulse(f"chat-item-{key}", 800)
                time.sleep(0.3)
        elapsed = time.monotonic() - runner.t0
        if elapsed < 5.6:
            time.sleep(5.6 - elapsed)
        runner.mark("scenario_end")
    except Exception as exc:  # noqa: BLE001
        runner.check("intro", False, f"exception: {type(exc).__name__}: {exc}")
    reasons = list(runner.failures)
    duration = runner.marks.get("scenario_end", 0.0) - runner.marks.get("scenario_start", 0.0)
    if duration < 4.0:
        reasons.append(f"duration {duration:.1f}s < 4s")
    return _finalize_take(scenario, take_idx, context, tmp_dir, runner, reasons, None)


def build_selection(
    outcomes: list[TakeOutcome], n_valid: int, scenario_nums: list[int]
) -> dict[str, Any]:
    """Deterministic best-take choice: lower latency, then shorter duration."""
    selection: dict[str, Any] = {}
    for scenario in ["intro", *[f"s{n}" for n in scenario_nums]]:
        mine = [o for o in outcomes if o.scenario == scenario]
        valid = sorted(
            [o for o in mine if o.valid], key=lambda o: (o.latency_s, o.visual_s)
        )
        chosen = valid[: max(1, n_valid)]
        selection[scenario] = {
            "chosen": [o.video for o in chosen if o.video],
            "n_valid": len(valid),
            "rejected": [
                {"take": o.take, "reasons": o.reasons}
                for o in mine
                if not o.valid
            ],
            "all": [
                {
                    "take": o.take,
                    "valid": o.valid,
                    "latency_s": o.latency_s,
                    "visual_s": o.visual_s,
                    "video": o.video,
                }
                for o in mine
            ],
        }
    return selection


def run_takes_mode(args: argparse.Namespace, scenario_nums: list[int]) -> int:  # noqa: ANN001
    n_valid = max(1, args.takes)
    TAKES_DIR.mkdir(parents=True, exist_ok=True)
    outcomes: list[TakeOutcome] = []
    print(f"[takes] target: {n_valid} valid take(s) per scenario → {TAKES_DIR}")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        warmup_ollama()
        outcomes.append(run_intro_take(browser, 0, args.base_url))
        for n in scenario_nums:
            attempt = 0
            got = 0
            while got < n_valid and attempt < n_valid + 2:
                attempt += 1
                print(f"[take] s{n} attempt {attempt}/{n_valid + 2}")
                outcome = run_scenario_take(browser, n, attempt, args.base_url)
                outcomes.append(outcome)
                if outcome.valid:
                    got += 1
                else:
                    warmup_ollama()
            if got < n_valid:
                print(f"[WARN] s{n}: only {got}/{n_valid} valid takes")
        browser.close()
    selection = build_selection(outcomes, n_valid, scenario_nums)
    selection_file = TAKES_DIR / "selection.json"
    selection_file.write_text(
        json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[takes] selection → {selection_file}")
    ok = all(
        selection[f"s{n}"]["n_valid"] >= 1 for n in scenario_nums
    )
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--record", action="store_true", help="headed + video + narration pauses")
    mode.add_argument("--test", action="store_true", help="headless, no pauses, exit 1 on failure")
    mode.add_argument(
        "--takes",
        type=int,
        default=0,
        metavar="N",
        help="record N independent valid takes per scenario (video pipeline)",
    )
    parser.add_argument("--scenario", type=int, choices=[1, 2, 3, 4], help="run one scenario")
    parser.add_argument("--base-url", default="http://localhost:8000")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    check_health(args.base_url)
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    scenario_nums = [args.scenario] if args.scenario else [1, 2, 3, 4]
    if args.takes > 0:
        return run_takes_mode(args, scenario_nums)
    record = not args.test

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

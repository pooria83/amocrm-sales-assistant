# Sales Assistant for AmoCRM — Demo Prototype

[![CI](https://github.com/pooria83/amocrm-sales-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/pooria83/amocrm-sales-assistant/actions/workflows/ci.yml)

**Русский:** [README.md](README.md)

A sales-manager prototype: it takes a customer message, looks the answer up in a short knowledge base (BM25) and produces **two strictly separated blocks** — a polite customer reply and internal upsell/cross-sell hints — exactly the way a manager works in the AmoCRM dialog window (the «Чат» and «Примечание» tabs).

Everything runs **offline and for free**: a local LLM (Ollama + `qwen2.5:7b`), no paid APIs.

![Interface: customer reply and internal hint](docs/screenshot.png)

> The «TeamFlow» product, prices and companies are fictional demo data. No AmoCRM account is connected: the interface mirrors dialog patterns but has no real API or webhooks.

## Quick start (Docker)

### Requirements

- Docker Desktop (Docker + Compose)
- Ollama on the host with the models:

```bash
ollama pull qwen2.5:7b
ollama pull qwen2.5:3b
```

### Run

```bash
cp .env.example .env
docker compose up --build -d   # or: make up
make warmup                    # warm the model before recording the demo
open http://localhost:8000
```

Compose runs **two separate containers**:

| Container | What's inside | Host port |
|---|---|---|
| `frontend` | nginx serving the React build (`frontend/Dockerfile`) | `8000 → 80` |
| `backend` | FastAPI + KB (`Dockerfile`) | not published (network-internal only) |

nginx serves the static build and proxies `/api/*` to `backend:8000`. The LLM stays **on the host** (Metal GPU on macOS): the container reaches `http://host.docker.internal:11434`.

- Linux: Ollama must listen on all interfaces — `OLLAMA_HOST=0.0.0.0`.
- Without a local Ollama (slow, CPU only): `docker compose --profile ollama up` with `OLLAMA_BASE_URL=http://ollama:11434`.
- `GET /api/health` always answers `200`; the `ollama` field honestly shows `reachable` / `unreachable`. The app and its template replies work even with the model turned off.

### Useful commands

| Command | What it does |
|---|---|
| `make up` / `make down` | start / stop both containers |
| `make logs` | `backend` + `frontend` logs |
| `make warmup` | one Ollama call with `keep_alive=30m` (pre-demo warm-up) |
| `make test` | `pytest` (132 tests) |
| `make lint` | `ruff` + `oxlint` |
| `make eval` | retrieval eval set + threshold calibration |

## Development mode

```bash
uv sync
uv run uvicorn backend.app:app --port 8000   # API; also serves frontend/dist if present

npm --prefix frontend ci
npm --prefix frontend run dev                # Vite on :5173, /api proxy → :8000
```

## Architecture

Principle: **deterministic first, LLM second.** Retrieval and upsell candidates are decided by code; the model only phrases text.

```
message + history + deal card
  → language detection (ru/en; short messages inherit the conversation)
  → BM25 over the KB (RU+EN, snowball stemming, threshold 2.5)
  → rule engine (intent + upsell triggers from KB and deal data)
  → Ollama qwen2.5:7b, structured JSON (temperature 0.2, seed 42)
  → 6 validators: schema · candidates · language · numbers · leakage · length
       (one retry with a stricter reminder → otherwise a template reply)
  → UI: customer reply (editable) + yellow «Manager only» panel
```

Key decisions:

- **Rules own the recommendations.** The rule engine returns candidate `id`s (`upsell`/`cross_sell`); the LLM receives only those and writes the wording. The validator drops any `id` outside the list — the model cannot «invent» an upsell.
- **`kb_refs` is filled by the backend** from retrieval results (matches above the threshold), never by the model: the UI shows them as «Sources» chips.
- **Two independent contracts** — `customer_reply` and `internal_sales_hints`: separate API fields, separate validators, separate React components, separate destinations (chat message vs internal note).
- **No KB match → the LLM is not called at all** — an honest template reply and an «escalate» note.

## Guardrails

1. **BM25 threshold (2.5)** — below it: template reply, no invented facts.
2. **Numeric guardrail with units** — numbers in the reply are extracted as `(value, unit)` (`%`, ₽, users, days) and checked against KB `facts`, deal data and the customer's own numbers. **Percentages come only from KB** — protection against the «give me a 90% discount» injection. Denials of the customer's percentage («20%, not 80%») are stripped from the reply before validation: echoing the customer's percentage is never a promise, and it must not reach the customer text anyway.
3. **Injection** — customer text is wrapped in `<customer_message>` and declared as data, not instructions; the reply is parsed against a JSON schema.
4. **Leakage protection** — the customer reply must not contain internal hint text, candidate `id`s or words like «upsell/cross-sell»; otherwise — retry, then template.
5. **Reply language = customer language** (RU/EN); hints are in the manager's UI language.
6. **One retry** with a stricter reminder, then a safe template; LLM unavailable → the same template plus the found articles.

## Retrieval evaluation and threshold calibration

`make eval` (15 cases: RU/EN, typos, morphology, short messages, injection, 2 no-match):

| Metric | Value |
|---|---|
| hit@1 | 90 % (9/10) |
| hit@3 | 100 % (10/10) |
| grounded accuracy | 100 % (12/12) |
| language accuracy | 100 % (15/15) |
| threshold | **2.5** (worst «must match» — 2.74 on a typo; no-match — 0) |

## CI

[.github/workflows/ci.yml](.github/workflows/ci.yml) runs on every push/PR:

| Job | What it does |
|---|---|
| `backend` | `uv sync --frozen` → `ruff` → `pytest` → `eval` (gate: grounded < 100 % = red) |
| `frontend` | `npm ci` → `oxlint` → `vite build` |
| `docker` | `docker compose up --build --wait` → health through the nginx proxy → check that the React build is served |

Ollama is unavailable in CI — `/api/health` allows for that (`unreachable` with `status: ok`), LLM tests are mocked.

## Demo and e2e (Playwright)

One script, two modes: video recording for the demo and a fast e2e run. Runs are **real**: the script hits the running app and checks the live `/api/assist` — no mocks.

Prerequisites: the app on `http://localhost:8000` (`make up`) and a warm model (`make warmup`).

| Command | What it does |
|---|---|
| `make demo-setup` | `uv sync` + `playwright install chromium` (once) |
| `make demo-test` | headless, no pauses, same checks; exit 1 on failure |
| `make demo` | headed 1920×1080 recording → `demo/videos/*.webm` |

Direct flags: `python demo/run_demo.py [--record|--test] [--scenario N] [--base-url URL]`.

Output files:

- `demo/videos/<name>.webm` — the recorded run;
- `demo/videos/timeline.json` — segment timings (`intro`, `s1`–`s4`, seconds) for splicing voiceover/captions in `video/build_video.sh`;
- `demo/videos/fail-<sN>.png` — screenshot on failure.

What each of the 4 scenarios checks: BM25 matches and their scores, the model's reply (including «5», «20%», Cyrillic-free EN, template fallback), the customer-reply / internal-hint split, no leakage of internal text or `id`s into the reply, the «Send to chat» button (bubble in the dialog) and «Add note» (yellow note, not a message).

## Evaluation via MCP: 100 cases

End-to-end checking goes through an MCP server: [`mcp/server.py`](mcp/server.py) exposes three tools (`get_health`, `retrieve_kb`, `assist_manager`), and [`mcp/run_harness.py`](mcp/run_harness.py) drives **100 cases** from [`mcp/cases.yaml`](mcp/cases.yaml) through them: happy-path, morphology («тариф/тарифы/тарифа»), objections, upsell rules, short messages with language inheritance, no-match, injections, numeric traps, mixed RU/EN.

The app must be up (`make up`) and the model warm (`make warmup`).

| Command | What it does |
|---|---|
| `make mcp` | full run of all 100 cases |
| `uv run python mcp/run_harness.py --only ru01,tr04` | targeted run by prefix |
| `… --md mcp/RESULTS.md` | copy of the report for review |

Every run writes into `mcp/out/<timestamp>/`: `cases.jsonl` (all data and checks per case, incremental), `report.md` (detailed report: BM25 output, reply, validation, hints, ✅/❌ per check), `summary.json`. `mcp/RESULTS.md` is a local copy of the latest report, git-ignored (generated, never committed).

Latest full run (`qwen2.5:7b`, threshold 2.5): **100/100 PASS** · hit@1 78/84 (93 %) · hit@3 84/84 (100 %) · average latency ~10 s. The single hit@1 miss is the documented `plan-start` vs `plan-business` case on shared words («план», «цена», «пользователь»): the needed article is always in the top-3.

## How I built this with AI

The build was **vibe-coded**: the code was generated by the coding agent **opencode**, facts and decisions were pinned in the frozen specification `CONTEXT.md`, and the commits and checks are mine.

### What opencode generated

- the project scaffold (uv + FastAPI + Vite/React/shadcn, Docker, tests);
- `backend/`: KB loader, BM25 retrieval with stemming, language detection, rule engine, Ollama client with structured output, six validators, `/api/assist` orchestration, fallback templates;
- frontend components per §5a (containers only in `AssistantPanel`/`ConversationPanel`, typed reply/hints contracts);
- the pytest suite and the eval runner;
- the CI workflow.

### What I changed by hand

- the KB facts (21 articles, only the allowed numbers from the spec) and the RU/EN texts;
- threshold calibration and the decision that reply percentages come only from the KB;
- the seed data of the four scenarios and the i18n wording;
- splitting Docker into two containers (nginx + backend) and the proxy config;
- every git message — `git diff` before each commit.

### What broke

- `pydantic-core` wouldn't build on Python 3.14 → the project moved to Python 3.12 via `uv`;
- `Tooltip` without `TooltipProvider` crashed the UI (caught by the ErrorBoundary during a browser smoke test);
- the internal escalation note rendered only in the button but not in the panel;
- hints were pushed below the fold — the panel was brought to a visible state with auto-scroll;
- the chat preview showed the internal note instead of the last message;
- piping `pytest | tail` hid the exit code — an `&&` chain became mandatory for every check;
- «скидка 90%» in the customer's message triggered a plan-enterprise upsell — unit-blind numbers were excluded from the target scan;
- «How much…?» collapsed to «much» after stopword filtering and read as an objection — stopwords and phrases fixed;
- on «how much for a year» the model insistently computed totals (and got them wrong: 9,540 ₽ instead of 9,504) — hardened the prompt, named the offending number in the reminder, and reformulated the trap case;
- the «not 80%» denial failed the numeric check — we learned to distinguish a denial of the customer's percentage from a promise and to strip it before validation.

### How I verified

- `pytest` — 132 tests (guardrail, leakage, no-match, rule engine, API);
- `ruff` + `oxlint` + Vite build;
- `make eval` with the grounded-accuracy gate;
- a browser smoke test of all 4 scenarios via Playwright against the real `qwen2.5:7b` (real replies, checking numbers, language and leakage);
- the full 100-case MCP run (`make mcp`) — **100/100 PASS**, hit@3 100 %;
- a full Docker run: both containers healthy, `/api/health` through nginx.

### Development-time vs runtime AI

- **Development-time AI** — opencode (coding agent), which wrote this code.
- **Runtime AI** — Ollama + `qwen2.5:7b`: phrasing the reply and the reasons over already-chosen facts only.
- **Deterministic logic** — Python: BM25, rule engine, validators, fallback templates.

The product is not an autonomous agent; it is AI-assisted software development around a guarded, deterministic pipeline.

### Key prompts

```text
1. In CONTEXT.md — the frozen project specification. Implement strictly
   following it, step by step in the order of §21, commit after each step
   with small Conventional Commits. Add nothing beyond the specification.

2. Scaffold: git init, uv project on Python 3.12, FastAPI with /api/health,
   Vite React-TS + Tailwind + shadcn/ui, ruff/pytest, Dockerfile + compose.
   Verify docker compose up --build and health BEFORE any feature work.

3. backend/retriever.py per §16: RU/EN tokenization, snowball stemming,
   BM25 (k1=1.5, b=0.75, top_k=3), the /api/retrieve endpoint;
   a 15-case eval; calibrate the threshold and write it into the README.

4. backend/validators.py per §17: six checks, the numeric one —
   fact-aware: (value, unit) pairs, percentages only from KB facts,
   so the «give me a 90% discount» injection never passes.

5. Frontend strictly per §5a: no monolithic App.tsx; containers only in
   AssistantPanel and ConversationPanel; CustomerReplyCard accepts ONLY the
   CustomerReply type, InternalHintsCard — ONLY InternalSalesHints;
   data-testid on every interactive element.

6. (personal) Split frontend and backend on Docker — two containers.
   CI on GitHub Actions; if CI goes red — fix it until it is green.
```

## Limitations

- **The numeric guardrail is best-effort**, not a proof: derived numbers (price × seats) and spelled-out numbers («five») are not verified; the prompt forbids computing totals.
- **Language detection** does not solve mixed messages, transliteration («skolko stoit») and very short opening messages (those inherit the conversation language).
- **BM25 does not understand pure paraphrase** with no shared words with the KB.
- **Plan and add-on names may appear in the customer reply** when they directly answer the question («WhatsApp is available on the Business plan»); the prompt forbids volunteering upgrades, but the validator does not block them — per the §17 contract it blocks internal texts (reason/talking_point), ids and markers.
- No persistence, authentication or multi-tenancy — just the KB file.
- The interface is an AmoCRM mock without logos and without a real API.

## Real AmoCRM adapter (not implemented)

What it would look like with the real API (description only, no code written):

1. AmoCRM `incoming_chat_message` webhook → the service's public endpoint;
2. the service assembles `message + history + deal` (deal card via the AmoCRM API) and calls `/api/assist`;
3. `customer_reply.text` is sent to the dialog via the messages API;
4. `internal_sales_hints` is saved as a note on the deal (AmoCRM stores notes separately — exactly like our UI).

## Stack

Python 3.12 · FastAPI · Pydantic v2 · rank-bm25 · snowballstemmer · httpx · Ollama (`qwen2.5:7b`/`3b`) · pytest · ruff · React + TypeScript + Vite + Tailwind + shadcn/ui · Docker (nginx + python) · GitHub Actions · Playwright (demo).

## Repository layout

```
kb/        kb.json (21 RU/EN articles) + schema + loader
backend/   app.py, retriever.py, language.py, rules.py, llm.py,
           validators.py, fallback.py, models.py, kb.py
frontend/  React app (components/{ui,crm,assistant,common},
           hooks, lib, data, i18n) + Dockerfile + nginx.conf
eval/      cases.yaml + run_eval.py
mcp/       server.py (MCP server), cases.yaml (100 cases),
           run_harness.py (end-to-end runner)
demo/      run_demo.py (Playwright: video recording + e2e)
tests/     pytest (132)
docs/      screenshot.png
.github/   workflows/ci.yml
```

.PHONY: up down logs warmup test lint eval demo demo-setup demo-test mcp script-check verify

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f backend frontend

# Load qwen2.5:7b into Ollama memory before recording (keeps demo latency low)
warmup:
	curl -s http://localhost:11434/api/chat -d '{"model":"qwen2.5:7b","messages":[{"role":"user","content":"hi"}],"keep_alive":"30m","stream":false}' | head -c 200

test:
	uv run pytest

lint:
	uv run ruff check .
	npm --prefix frontend run lint

# STEP 7 hygiene: no CJK / mixed-script words in tracked non-Python files
script-check:
	uv run python eval/check_scripts.py

eval:
	uv run python eval/run_eval.py

demo-setup:
	uv sync
	uv run playwright install chromium

demo:
	uv run python demo/run_demo.py --record

demo-test:
	uv run python demo/run_demo.py --test

# 100-case MCP evaluation; needs the app (make up) and a warm model (make warmup)
mcp:
	uv run python mcp/run_harness.py

# Everything that can run offline (no Ollama, no Docker): ruff, script
# hygiene, pytest, frontend lint+build, retrieval/language eval.
verify: lint script-check test
	npm --prefix frontend run build
	uv run python eval/run_eval.py

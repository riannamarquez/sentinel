# Sentinel developer targets. Everything runs through uv so versions come from uv.lock.
UV ?= uv
PORT ?= 8000
# Live LLM recordings; run-replay reads the same file.
LLM_DB ?= data/demo.llm.db
SERVE = $(UV) run --frozen uvicorn --factory sentinel.api.app:create_app --host 127.0.0.1 --port $(PORT)

# Refuse a missing .env or one with placeholders left, then export it. Only variable names are ever printed.
LOAD_ENV = test -f .env || { echo "No .env. Run: cp .env.example .env, then fill in SENTINEL_LLM_MODEL and GEMINI_API_KEY."; exit 1; }; \
	left=$$(grep -E '<|PASTE_KEY_HERE' .env | cut -d= -f1 | tr '\n' ' '); \
	test -z "$$left" || { echo ".env still has placeholders for: $$left- edit .env and try again."; exit 1; }; \
	set -a; . ./.env; set +a; \
	test -n "$$SENTINEL_LLM_MODEL" -a -n "$$GEMINI_API_KEY" || { echo ".env must set SENTINEL_LLM_MODEL and GEMINI_API_KEY."; exit 1; }

.PHONY: install test feasibility feasibility-results fixtures run run-live run-replay

install:
	$(UV) sync --frozen

test: install
	$(UV) run --frozen pytest

feasibility: install
	$(UV) run --frozen python scripts/feasibility.py

feasibility-results: install
	sh scripts/write_feasibility_results.sh

fixtures: install
	$(UV) run --frozen python scripts/make_fixtures.py

# Safe fallback demo: heuristic Red, fixture Blue, no network.
run: install
	$(SERVE)

# Live Gemini for Red and Blue, recording every response to $(LLM_DB). The lab database starts
# empty each time so the first round is lab-0001/run-000001, the IDs run-replay will see too.
run-live:
	@$(LOAD_ENV); \
	mkdir -p data && rm -f data/live.db data/live.db-wal data/live.db-shm; \
	echo "Live LLM mode: Red=$${SENTINEL_RED:-heuristic}, model $$SENTINEL_LLM_MODEL, recording to $(LLM_DB)"; \
	SENTINEL_LLM_MODE=live SENTINEL_DB=data/live.db SENTINEL_LLM_DB=$(LLM_DB) $(SERVE)

# Replays $(LLM_DB) with no network calls; a miss is an error for Blue and a logged fallback for Red.
# Only the first round after start replays (it gets the recorded IDs), so restart to replay again.
run-replay:
	@$(LOAD_ENV); \
	test -s $(LLM_DB) || { echo "No recordings at $(LLM_DB). Record a round with make run-live first."; exit 1; }; \
	mkdir -p data && rm -f data/replay.db data/replay.db-wal data/replay.db-shm; \
	echo "Replay LLM mode: Red=$${SENTINEL_RED:-heuristic}, model $$SENTINEL_LLM_MODEL, replaying $(LLM_DB)"; \
	SENTINEL_LLM_MODE=replay SENTINEL_DB=data/replay.db SENTINEL_LLM_DB=$(LLM_DB) $(SERVE)

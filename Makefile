# Sentinel developer targets. Everything runs through uv so versions come from uv.lock.
UV ?= uv
PORT ?= 8000

.PHONY: install test feasibility feasibility-results fixtures run

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

run: install
	$(UV) run --frozen uvicorn sentinel.api.app:app --host 127.0.0.1 --port $(PORT)

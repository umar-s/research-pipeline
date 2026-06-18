# voxscribe — developer Makefile.
#
# Targets are thin uv-wrappers so the plugin has zero environment assumptions
# beyond `uv` (https://docs.astral.sh/uv/). All deps are installed ephemerally.

SHELL := /usr/bin/env bash

.PHONY: help test test-fast test-slow lint clean

help: ## show available targets
	@awk 'BEGIN {FS = ":.*##"; printf "voxscribe — make targets:\n\n"} \
	      /^[a-zA-Z0-9_.-]+:.*##/ {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

test: test-fast ## fast tests only (preprocess golden — no model download)

test-fast: ## preprocess golden tests (no transformers/torch needed)
	uv run --with pytest pytest scripts/tests -m "not slow" -v

test-slow: ## sbert + dialogify tests (downloads ~700 MB on first run)
	uv run --with pytest --with torch --with transformers \
	    pytest scripts/tests -m slow -v

lint: ## ruff check on the scripts directory
	uv run --with ruff ruff check scripts/

clean: ## remove pytest/__pycache__ artifacts
	find . -type d \( -name __pycache__ -o -name .pytest_cache \) -exec rm -rf {} + 2>/dev/null || true

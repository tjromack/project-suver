# Project Suver — task runner.
# Fresh-install-safe: `setup` installs with the venv's OWN Python (not the parse-time PY), so a brand-new clone
# just works — the lesson from the suite's `make setup` first-run bug, fixed here from day one. See CLAUDE.md.

ifeq ($(OS),Windows_NT)
	VENV_PY := .venv/Scripts/python.exe
else
	VENV_PY := .venv/bin/python
endif
# For running tasks: use the venv if present, else system python.
PY := $(if $(wildcard $(VENV_PY)),$(VENV_PY),python)

HOST ?= 127.0.0.1
PORT ?= 8000
TEXT ?= Contact Jane Roe (SSN 123-45-6789). The report finds throughput rose twelve percent this quarter.
FILE ?= data/samples/sample.txt

.PHONY: help setup serve test ingest sanitize summarize fmt
help:
	@echo "setup      - create .venv and install requirements (into the venv explicitly)"
	@echo "serve      - start the hub + the Summarize tool (uvicorn --reload)"
	@echo "test       - run pytest"
	@echo "ingest     - a real file -> extracted text (FILE=path)"
	@echo "sanitize   - the safe text + 'N sensitive items handled' (TEXT=...)"
	@echo "summarize  - a cited summary: key points + withheld (TEXT=...)"
	@echo "fmt        - format + lint with ruff (if installed)"

# --- fresh-install-safe setup: create the venv, then install with the VENV's python explicitly ---
setup:
	python -m venv .venv
	$(VENV_PY) -m pip install --upgrade pip
	$(VENV_PY) -m pip install -r requirements.txt

serve:
	$(PY) -m uvicorn app.main:app --reload --host $(HOST) --port $(PORT)

test:
	$(PY) -m pytest -q

ingest:
	$(PY) -m app.show_ingest "$(FILE)"

sanitize:
	$(PY) -m app.show_sanitize "$(TEXT)"

summarize:
	$(PY) -m app.show_summarize "$(TEXT)"

fmt:
	$(PY) -m ruff format app tests
	$(PY) -m ruff check --fix app tests

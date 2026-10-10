PY := .venv/bin/python
PORT ?= 8741

.PHONY: install lint fmt test gate run push-hosts

install:
	python3 -m venv .venv
	.venv/bin/pip install -q -r requirements.txt

lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

fmt:
	.venv/bin/ruff check --fix .
	.venv/bin/ruff format .

test:
	.venv/bin/pytest

# The same script runs on Windows without make: .venv\Scripts\python scripts\gate.py
gate:
	$(PY) scripts/gate.py

run:
	PYTHONPATH=src $(PY) -m equinox.server --port $(PORT)

# Push the current branch to both hosts: origin is GitLab, github is GitHub.
push-hosts:
	git push origin HEAD
	git push github HEAD

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

gate: lint test

run:
	PYTHONPATH=src $(PY) -m equinox.server --port $(PORT)

# Push main to the github and gitlab remotes added by scripts/link-hosts.sh.
push-hosts:
	git push github HEAD:main
	git push gitlab HEAD:main

.PHONY: install test lint typecheck seed serve

install:
	python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'

test:
	pytest -q

lint:
	ruff check app tests scripts

typecheck:
	mypy app

seed:
	python -m scripts.seed

serve:
	uvicorn app.main:app --reload --port 8080

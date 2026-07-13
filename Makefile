.PHONY: install demo test lint typecheck seed serve

install:
	python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'

demo:
	refund-agent demo

test:
	pytest -q

lint:
	ruff check app tests

typecheck:
	mypy app

seed:
	python -m app.integrations.graph.seed

serve:
	uvicorn app.main:app --reload --port 8080

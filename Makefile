.PHONY: install test lint typecheck seed serve web

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

# The UI, against a local `make serve`. Needs web/.env.local (see web/.env.example);
# with PROXY_SHARED_SECRET blank on both sides the gate is off, which is what you want here.
web:
	cd web && npm install && npm run dev

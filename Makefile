.PHONY: fetch sim all validate validate-quick demo test test-slow

fetch:  ## the only command that uses the network
	uv run python -c "from core.config import load; from ingest import fetch_all; fetch_all(load()[0])"

sim:  ## synthetic region with known truth, every stage file
	uv run python -m sim

all:  ## reference -> coverage -> detect -> match -> aggregate -> forecast -> detectors -> fuse -> patrol -> export
	uv run python -m scripts.run_all

validate:  ## reports/validation.json (~35 min on the simulator)
	uv run python -m validate

validate-quick:  ## the same report with the reduced counts in config validate.quick; marked "mode": "quick"
	uv run python -m validate --quick

demo:  ## make all on top of an existing reports/validation.json (never runs validate)
	uv run python -m scripts.demo

test:
	uv run ruff check .
	uv run ruff format --check .
	uv run basedpyright
	uv run tach check
	uv run pytest -q --tb=short

test-slow:  ## the slow tests (whole simulated seasons, ~5 min); CI runs them after merges
	uv run pytest -q --tb=short -m slow

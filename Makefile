.PHONY: test lint format check

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

check:
	@./scripts/check.sh

.PHONY: test lint fix ci

test:
	BOT_MODE=TEST pytest

lint:
	ruff check .
	ruff format --check .

fix:
	ruff check . --fix
	ruff format .

ci: lint test

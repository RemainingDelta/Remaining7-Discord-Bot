.PHONY: test lint fix ci up

test:
	BOT_MODE=TEST pytest

lint:
	ruff check .
	ruff format --check .

fix:
	ruff check . --fix
	ruff format .

ci: lint test

up:
	python main.py

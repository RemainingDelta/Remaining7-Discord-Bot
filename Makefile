.PHONY: test lint fix ci up commit

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

commit:
ifndef m
	$(error m is not set. Usage: make commit m="your commit message")
endif
	git add .
	git commit -m "$(m)"
	git push

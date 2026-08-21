.PHONY: test lint fix ci up commit

# Use the project venv when it exists so `make test` does not fall through to
# whatever `pytest` happens to be on PATH (e.g. a system/conda install missing
# the runtime deps). CI has no venv and lands on python3, which is correct there.
PYTHON := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

test:
	BOT_MODE=TEST $(PYTHON) -m pytest

lint:
	@ruff check . -q
	@ruff format --check .
	@echo "Lint passed"

fix:
	ruff check . --fix
	ruff format .

ci:
	@$(MAKE) lint && $(MAKE) test && printf "\033[1;32mAll checks passed!\033[0m\n"

up:
	python main.py

commit:
ifndef m
	$(error m is not set. Usage: make commit m="your commit message")
endif
	git add .
	git commit -m "$(m)"
	git push
	
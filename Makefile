.PHONY: test lint fix ci up commit

test:
	BOT_MODE=TEST pytest

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
	
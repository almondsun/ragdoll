.PHONY: check format test

check:
	ruff format --check .
	ruff check .
	mypy src
	pytest --cov --cov-branch
	python -m build

format:
	ruff format .
	ruff check --fix .

test:
	pytest


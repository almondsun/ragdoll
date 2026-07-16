.PHONY: brand check format screenshot test

brand:
	python scripts/render_brand.py

check:
	ruff format --check .
	ruff check .
	mypy src
	pytest --cov --cov-branch
	python -m build

format:
	ruff format .
	ruff check --fix .

screenshot:
	python scripts/capture_tui.py

test:
	pytest

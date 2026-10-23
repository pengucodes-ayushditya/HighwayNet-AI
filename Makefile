.PHONY: install app test lint format benchmark fetch
install:
	uv sync --frozen
app:
	uv run streamlit run app.py
test:
	uv run pytest --cov=highwaynet --cov-report=term-missing
lint:
	uv run ruff check .
	uv run ruff format --check .
format:
	uv run ruff check . --fix
	uv run ruff format .
benchmark:
	uv run highwaynet benchmark --out results/local/demo
fetch:
	uv run highwaynet fetch

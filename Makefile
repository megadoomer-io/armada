.PHONY: deps lint format typecheck test test-unit test-integration validate clean

deps:           ## Install/sync dependencies
	@uv sync --all-groups

lint:           ## Run linter
	@uv run ruff check .

format:         ## Format code
	@uv run ruff format .
	@uv run ruff check --fix .

typecheck:      ## Run type checker
	@uv run mypy src/armada

test:           ## Run all tests
	@uv run pytest

test-unit:      ## Run unit tests only
	@uv run pytest -m unit

test-integration:  ## Run integration tests only
	@uv run pytest -m integration

validate:       ## Run all checks (CI equivalent)
	@$(MAKE) lint
	@$(MAKE) typecheck
	@$(MAKE) test

clean:          ## Remove build artifacts
	@rm -rf .mypy_cache .pytest_cache .ruff_cache htmlcov coverage.xml test-results

.PHONY: setup test lint run clean help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup: ## One-command setup: install dependencies
	python -m venv venv
	. venv/bin/activate && pip install -r requirements.txt
	@echo "Setup complete. Run 'source venv/bin/activate' then 'make run'"

test: ## Run test suite
	python -m pytest tests/ -v

lint: ## Run linters (ruff + black)
	ruff check .
	black --check .

format: ## Auto-format code
	ruff check --fix .
	black .

run: ## Start the dashboard
	python app.py

clean: ## Remove build artifacts
	rm -rf __pycache__ .pytest_cache .ruff_cache venv *.db
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true


# Default target
.DEFAULT_GOAL := help

# Variables
PYTHON := poetry run python
POETRY := poetry run
SRC_DIRS := streamlit data

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Targets:'
	@egrep '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

format: ## Format code with Ruff
	@echo "🛠️  Formatting code..."
	$(POETRY) ruff format $(SRC_DIRS)

lint-fix: ## Automatically fix linting issues where possible (excludes tests/)
	@echo "🔧 Fixing linting issues..."
	$(POETRY) ruff check --fix --exit-zero $(SRC_DIRS)

lint: ## Run all linting checks (excludes tests/)
	@echo "🔍 Running linting checks..."
	$(POETRY) ruff check $(SRC_DIRS)

check-types: ## Run static type checking with mypy (excludes tests/)
	@echo "🔎 Running type checks..."
	$(POETRY) mypy --config-file mypy.ini $(SRC_DIRS)

test: ## Run tests with coverage
	@echo "\n🔍 Running tests..."
	$(POETRY) pytest tests/ -v --cov=. --cov-report=term-missing --cov-report=html

security: ## Run security checks with bandit
	@echo "🔒 Running security checks..."
	$(POETRY) bandit -r $(SRC_DIRS)

update: ## Update all dependencies
	@echo "🔄 Updating dependencies..."
	poetry update --no-cache

clean: ## Remove all cache and build files
	@echo "🧹 Cleaning up..."
	find . -type f -name '*.py[co]' -delete
	find . -type d -name '__pycache__' -exec rm -rf {} +
	find . -type d -name '.pytest_cache' -exec rm -rf {} +
	find . -type d -name '.mypy_cache' -exec rm -rf {} +
	rm -rf .coverage htmlcov/ .pytest_cache/ .tox/ .ruff_cache/ .pylint.d/
	rm -f coverage.xml *.cover
	rm -rf build/ dist/ .eggs/
	find . -name '*.egg-info' -exec rm -rf {} +
	find . -name '.DS_Store' -exec rm -f {} \;


all: format lint-fix check-types test security update clean
	@echo "✅ All tests passed successfully! 🎉"
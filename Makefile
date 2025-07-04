.PHONY: help install install-dev test clean lint format type-check run docs

# Default target
help:
	@echo "RefChecker - Academic Paper Reference Validation Tool"
	@echo ""
	@echo "Available targets:"
	@echo "  install      Install package in current environment"
	@echo "  install-dev  Install package with development dependencies"
	@echo "  test         Run all validation tests"
	@echo "  clean        Clean up generated files"
	@echo "  lint         Run code linting"
	@echo "  format       Format code with black and isort"
	@echo "  type-check   Run type checking with mypy"
	@echo "  run          Run refchecker with example paper"
	@echo "  docs         Generate documentation"
	@echo "  download-db  Download Semantic Scholar database"

# Install package
install:
	pip install -e .

# Install with development dependencies
install-dev:
	pip install -e ".[dev]"

# Run tests
test:
	python scripts/run_tests.py

# Clean up generated files
clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf logs/
	rm -rf debug/
	rm -rf output/
	rm -rf validation_output/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/

# Lint code
lint:
	flake8 src/ tests/ scripts/
	
# Format code
format:
	black src/ tests/ scripts/
	isort src/ tests/ scripts/

# Type check
type-check:
	mypy src/

# Run with example
run:
	python refchecker.py --paper 1706.03762 --debug

# Download database
download-db:
	python scripts/download_db.py --field "computer science" --start-year 2020

# Generate docs
docs:
	cd docs && make html
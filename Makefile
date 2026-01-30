.PHONY: help install install-dev test clean lint format type-check run docs \
	docker-build docker-run docker-test docker-push

# Default target
help:
	@echo "RefChecker - Academic Paper Reference Validation Tool"
	@echo ""
	@echo "Available targets:"
	@echo "  install          Install package in current environment"
	@echo "  install-dev      Install package with development dependencies"
	@echo "  test             Run all validation tests"
	@echo "  clean            Clean up generated files"
	@echo "  lint             Run code linting"
	@echo "  format           Format code with black and isort"
	@echo "  type-check       Run type checking with mypy"
	@echo "  run              Run refchecker with example paper"
	@echo "  docs             Generate documentation"
	@echo "  download-db      Download Semantic Scholar database"
	@echo ""
	@echo "Docker targets:"
	@echo "  docker-build     Build Docker image"
	@echo "  docker-run       Run Docker container"
	@echo "  docker-test      Build and test Docker image"
	@echo "  docker-push      Push images to GitHub Container Registry"

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
	python run_refchecker.py --paper 1706.03762 --debug

# Download database
download-db:
	python scripts/download_db.py --field "computer science" --start-year 2020

# Generate docs
docs:
	cd docs && make html

# =============================================================================
# Docker targets
# =============================================================================

DOCKER_IMAGE = ghcr.io/markrussinovich/refchecker
VERSION = $(shell python -c "import sys; sys.path.insert(0, 'src'); from refchecker.__version__ import __version__; print(__version__)" 2>/dev/null || echo "dev")

# Build standard Docker image
docker-build:
	docker build -t $(DOCKER_IMAGE):latest -t $(DOCKER_IMAGE):$(VERSION) .

# Run Docker container
docker-run:
	docker run -it --rm \
		-p 8000:8000 \
		-v refchecker-data:/app/data \
		--env-file .env \
		$(DOCKER_IMAGE):latest

# Build and test Docker image (for CI)
docker-test:
	docker build -t $(DOCKER_IMAGE):test .
	docker run --rm -d --name refchecker-test -p 8001:8000 $(DOCKER_IMAGE):test
	@echo "Waiting for container to start..."
	@sleep 5
	@curl -sf http://localhost:8001/api/health && echo "Health check passed!" || (docker logs refchecker-test && docker stop refchecker-test && exit 1)
	@docker stop refchecker-test
	@echo "Docker test passed!"

# Push images to GitHub Container Registry (requires docker login)
docker-push:
	docker push $(DOCKER_IMAGE):latest
	docker push $(DOCKER_IMAGE):$(VERSION)
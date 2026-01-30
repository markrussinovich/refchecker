# RefChecker Docker Image
# Multi-stage build for a self-contained application with bundled frontend
#
# Build: docker build -t refchecker .
# Run:   docker run -p 8000:8000 refchecker

# =============================================================================
# Stage 1: Build the frontend
# =============================================================================
FROM node:20-slim AS node-builder

WORKDIR /build

# Copy package files first for better layer caching
COPY web-ui/package*.json ./

# Install dependencies
RUN npm ci --no-audit --no-fund

# Copy source and build
COPY web-ui/ ./
RUN npm run build

# =============================================================================
# Stage 2: Build Python dependencies
# =============================================================================
FROM python:3.11-slim AS python-builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies (lightweight, no GPU libs)
COPY requirements-docker.txt .
RUN pip install --no-cache-dir --upgrade pip wheel && \
    pip install --no-cache-dir -r requirements-docker.txt

# =============================================================================
# Stage 3: Runtime image
# =============================================================================
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="RefChecker"
LABEL org.opencontainers.image.description="Academic paper reference validation tool"
LABEL org.opencontainers.image.source="https://github.com/markrussinovich/refchecker"
LABEL org.opencontainers.image.licenses="MIT"

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # PDF processing
    libmupdf-dev \
    # Fonts for thumbnail generation
    fonts-dejavu-core \
    # Health check
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user
RUN groupadd --gid 1000 refchecker && \
    useradd --uid 1000 --gid refchecker --shell /bin/bash --create-home refchecker

# Set working directory
WORKDIR /app

# Copy virtual environment from builder
COPY --from=python-builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source
COPY --chown=refchecker:refchecker src/ ./src/
COPY --chown=refchecker:refchecker backend/ ./backend/
COPY --chown=refchecker:refchecker pyproject.toml ./

# Copy bundled frontend from node builder
COPY --from=node-builder --chown=refchecker:refchecker /build/dist ./backend/static/

# Create data directory for persistent storage
RUN mkdir -p /app/data && chown refchecker:refchecker /app/data

# Environment variables
ENV PYTHONPATH="/app/src:/app" \
    PYTHONUNBUFFERED=1 \
    REFCHECKER_DATA_DIR="/app/data"

# Switch to non-root user
USER refchecker

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Default command
ENTRYPOINT ["python", "-m", "backend"]
CMD ["--host", "0.0.0.0", "--port", "8000"]

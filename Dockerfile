# RefChecker Python Workspace Container
FROM python:3.11-slim

# Set work directory
WORKDIR /workspace

# Install system dependencies (for optional features)
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements (if present)
COPY requirements.txt ./

# Install Python dependencies (core + optional)
RUN pip install --upgrade pip && \
    if [ -f requirements.txt ]; then pip install -r requirements.txt; fi

# Install optional/test/llm dependencies for full dev experience
RUN pip install '.[llm,dev,optional]' || true

# Copy the rest of the code
COPY . .

# Default command: open a shell
CMD ["bash"]

# ThreadWeave - Production Container Runtime
# Python 3.11-slim, zero external cloud dependencies, fully hermetic evaluation

FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libasound2-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code, scenarios, and tests
COPY threadweave/ ./threadweave/
COPY scenarios/ ./scenarios/
COPY tests/ ./tests/
COPY harness_adapter.py .
COPY run_harness.py .
COPY pyproject.toml .
COPY README.md .

# Run test suite and execute all scenarios by default
CMD ["python", "run_harness.py", "--all"]

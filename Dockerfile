# Stage 1: Build
FROM python:3.14.5-slim-bookworm AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy only the requirements file to take advantage of Docker's caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.14.5-slim-bookworm

RUN addgroup --system vocard \
    && adduser --system --ingroup vocard --home /home/vocard vocard

# Set the working directory
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    LOG_FILE_ENABLE=false \
    HOME=/home/vocard

# Copy installed Python packages from the builder stage
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages

# Copy the application code
COPY --chown=vocard:vocard . .

RUN mkdir -p /app/logs && chown -R vocard:vocard /app /home/vocard

USER vocard

# Run the application
CMD ["python", "-u", "main.py"]

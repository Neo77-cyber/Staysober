FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

# Install system dependencies for PostgreSQL and health checks
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    curl \ 
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . /app/

# Create a non-privileged user for security (Senior Dev move)
RUN adduser --disabled-password --gecos "" appuser
USER appuser

# Render will override the PORT env var, but 10000 is the default
CMD ["gunicorn", "turf_project.wsgi:application", "--bind", "0.0.0.0:10000"]
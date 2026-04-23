FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    curl \ 
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt


COPY . /app/


RUN adduser --disabled-password --gecos "" appuser && \
    chown -R appuser:appuser /app


USER appuser


# Gunicorn setup
CMD ["gunicorn", "turf_project.wsgi:application", "--bind", "0.0.0.0:10000"]
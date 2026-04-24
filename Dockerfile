FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app


RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    curl \ 
    && rm -rf /var/lib/apt/lists/*


COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt


COPY . /app/


RUN python manage.py collectstatic --noinput


RUN adduser --disabled-password --gecos "" appuser && \
    chown -R appuser:appuser /app


USER appuser




CMD ["gunicorn", "turf_project.wsgi:application", "--bind", "0.0.0.0:10000", "--log-level", "debug", "--access-logfile", "-"]
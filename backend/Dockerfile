# Django 6.0 requires Python 3.12+
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# psycopg[binary] ships wheels, so no libpq build deps are needed.
# curl is here only for the compose healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first so the pip layer caches across code changes
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN chmod +x /app/entrypoint.sh \
    && adduser --disabled-password --gecos "" --uid 1000 app \
    && mkdir -p /app/staticfiles \
    && chown -R app:app /app
USER app

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", "--access-logfile", "-"]

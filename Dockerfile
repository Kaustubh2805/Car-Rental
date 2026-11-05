FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        default-libmysqlclient-dev \
        gcc \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY . .

RUN SECRET_KEY=build-only-not-for-runtime \
    ALLOWED_HOSTS=localhost \
    DB_NAME=static_collection \
    DB_USER=static_collection \
    DB_PASSWORD=static_collection \
    DB_HOST=127.0.0.1 \
    DB_PORT=3306 \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    python manage.py collectstatic --noinput

RUN addgroup --system django \
    && adduser --system --ingroup django django \
    && mkdir -p /app/media \
    && chown -R django:django /app/media

USER django

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--config", "gunicorn.conf.py"]

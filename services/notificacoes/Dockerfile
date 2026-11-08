# syntax=docker/dockerfile:1
# Build a partir da RAIZ do repositório: docker build -f services/notificacoes/Dockerfile .
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod PORT=8005
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app
WORKDIR /app
COPY libs/tcc_common /libs/tcc_common
COPY services/notificacoes/requirements.txt services/notificacoes/requirements-dev.txt ./
ARG DEV=0
RUN pip install /libs/tcc_common && pip install -r requirements.txt \
    && if [ "$DEV" = "1" ]; then pip install -r requirements-dev.txt; fi
COPY services/notificacoes/ ./
RUN chmod +x entrypoint.sh && mkdir -p /app/media /app/staticfiles && chown -R app:app /app
USER app
EXPOSE 8005
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD curl -fsS http://localhost:8005/health/ || exit 1
ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "-c", "gunicorn.conf.py"]

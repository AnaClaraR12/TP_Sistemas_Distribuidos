"""Healthchecks: /health/ (liveness) e /ready/ (Postgres, Redis, RabbitMQ)."""

from __future__ import annotations

import socket

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health(request):
    return JsonResponse(
        {"status": "ok", "servico": getattr(settings, "SERVICO_NOME", "?"), "instancia": socket.gethostname()}
    )


def _checar_postgres() -> str:
    with connection.cursor() as cur:
        cur.execute("SELECT 1")
    return "ok"


def _checar_redis() -> str:
    from tcc_common.cache.redis import get_redis

    get_redis().ping()
    return "ok"


def _checar_rabbit() -> str:
    if not getattr(settings, "READY_CHECK_RABBITMQ", True):
        return "ignorado"
    from tcc_common.events.rabbit import abrir_conexao

    conn = abrir_conexao(timeout=3)
    conn.close()
    return "ok"


@require_GET
def ready(request):
    resultado: dict[str, str] = {}
    ok = True
    for nome, fn in (("postgres", _checar_postgres), ("redis", _checar_redis), ("rabbitmq", _checar_rabbit)):
        try:
            resultado[nome] = fn()
        except Exception as exc:  # noqa: BLE001 - healthcheck precisa capturar tudo
            ok = False
            resultado[nome] = f"falha: {exc.__class__.__name__}"
    return JsonResponse(
        {"status": "ok" if ok else "indisponivel", "dependencias": resultado}, status=200 if ok else 503
    )

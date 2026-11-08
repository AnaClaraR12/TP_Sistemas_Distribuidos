"""Conexão, topologia e publisher RabbitMQ (pika).

Topologia (idempotente):

* exchange ``tcc.events`` (topic, durable) e ``tcc.dlx`` (direct, durable);
* para cada binding de um consumer: fila ``<servico>.<routing_key>`` com
  ``x-dead-letter-exchange=tcc.dlx``; filas de retry ``<fila>.retry.N`` com TTL
  (backoff 10 s, 60 s, 5 min) que devolvem à fila original; e ``<fila>.dlq``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import pika
from django.conf import settings

logger = logging.getLogger(__name__)

EXCHANGE = "tcc.events"
DLX = "tcc.dlx"
RETRY_TTLS_MS = (10_000, 60_000, 300_000)


def abrir_conexao(timeout: int = 10) -> pika.BlockingConnection:
    params = pika.URLParameters(settings.RABBITMQ_URL)
    params.socket_timeout = timeout
    params.blocked_connection_timeout = timeout
    params.heartbeat = 60
    return pika.BlockingConnection(params)


def nome_fila(servico: str, binding: str) -> str:
    return f"{servico}.{binding.replace('#', 'todos').replace('*', 'qualquer')}"


@dataclass(frozen=True)
class FilasConsumer:
    principal: str
    retries: tuple[str, ...]
    dlq: str


def declarar_exchanges(canal) -> None:
    canal.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
    canal.exchange_declare(exchange=DLX, exchange_type="direct", durable=True)


def declarar_fila_consumer(canal, servico: str, binding: str, ttls: tuple[int, ...] = RETRY_TTLS_MS) -> FilasConsumer:
    """Declara fila principal + retries + DLQ para um binding. Idempotente."""
    declarar_exchanges(canal)
    fila = nome_fila(servico, binding)
    dlq = f"{fila}.dlq"
    canal.queue_declare(queue=dlq, durable=True)
    canal.queue_bind(queue=dlq, exchange=DLX, routing_key=dlq)
    canal.queue_declare(
        queue=fila,
        durable=True,
        arguments={"x-dead-letter-exchange": DLX, "x-dead-letter-routing-key": dlq},
    )
    canal.queue_bind(queue=fila, exchange=EXCHANGE, routing_key=binding)
    retries = []
    for i, ttl in enumerate(ttls, start=1):
        nome = f"{fila}.retry.{i}"
        canal.queue_declare(
            queue=nome,
            durable=True,
            arguments={"x-message-ttl": ttl, "x-dead-letter-exchange": "", "x-dead-letter-routing-key": fila},
        )
        retries.append(nome)
    return FilasConsumer(fila, tuple(retries), dlq)


class Publisher:
    """Publisher com *publisher confirms* e mensagens persistentes."""

    def __init__(self) -> None:
        self._conn: pika.BlockingConnection | None = None
        self._canal = None

    def _garantir_canal(self):
        if self._conn is None or self._conn.is_closed or self._canal is None or self._canal.is_closed:
            self._conn = abrir_conexao()
            self._canal = self._conn.channel()
            self._canal.confirm_delivery()
            declarar_exchanges(self._canal)
        return self._canal

    def publicar(self, envelope: dict, exchange: str = EXCHANGE, routing_key: str | None = None) -> None:
        canal = self._garantir_canal()
        canal.basic_publish(
            exchange=exchange,
            routing_key=routing_key or envelope["type"],
            body=json.dumps(envelope, ensure_ascii=False).encode(),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
                message_id=envelope["event_id"],
                correlation_id=envelope.get("correlation_id") or None,
                type=envelope["type"],
            ),
            mandatory=False,
        )

    def fechar(self) -> None:
        if self._conn and self._conn.is_open:
            self._conn.close()
        self._conn = None
        self._canal = None

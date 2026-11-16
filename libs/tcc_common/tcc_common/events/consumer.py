"""Consumer de eventos: idempotência, ack depois do commit, retry com backoff e DLQ.

Cada serviço registra ``{binding: handler}`` em ``settings.EVENT_HANDLERS``. Cada binding
vira uma fila própria, então quem decide o handler é o RabbitMQ, não este código.
Se o handler tiver o atributo ``falha_definitiva(envelope, exc)``, ele é chamado
quando as tentativas acabam, antes da mensagem ir para a DLQ.
"""

import json
import logging

import pika
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.utils.module_loading import import_string

from tcc_common import request_id_atual
from tcc_common.events import rabbit
from tcc_common.events.models import EventoProcessado

logger = logging.getLogger(__name__)

CABECALHO_TENTATIVAS = "x-tentativas"


def processar_evento(envelope, handler):
    """Roda o handler numa transação e marca o evento como processado.

    Devolve "processado" ou "duplicado". Se o handler levantar exceção, a transação
    é desfeita e o evento continua não processado (vai para retry).
    """
    event_id = envelope["event_id"]
    token = request_id_atual.set(envelope.get("correlation_id"))
    try:
        if EventoProcessado.objects.filter(event_id=event_id).exists():
            return "duplicado"
        try:
            with transaction.atomic():
                handler(envelope)
                EventoProcessado.objects.create(event_id=event_id, tipo=envelope["type"])
        except IntegrityError:
            # outro worker processou o mesmo event_id ao mesmo tempo
            if EventoProcessado.objects.filter(event_id=event_id).exists():
                return "duplicado"
            raise
        return "processado"
    finally:
        request_id_atual.reset(token)


class BaseConsumer:
    def __init__(self, servico, handlers, prefetch=10):
        self.servico = servico
        self.handlers = import_string(handlers) if isinstance(handlers, str) else handlers
        self.prefetch = prefetch
        self.filas = {}

    def declarar(self, canal):
        for binding in self.handlers:
            self.filas[binding] = rabbit.declarar_fila_consumer(canal, self.servico, binding)

    def _on_message(self, canal, method, properties, body, binding):
        filas = self.filas[binding]
        handler = self.handlers[binding]
        try:
            envelope = json.loads(body)
            tipo = envelope["type"]
        except (ValueError, KeyError, TypeError) as exc:
            # mensagem que nem é um envelope: tentar de novo não adianta
            logger.error("mensagem_invalida", extra={"fila": filas.principal, "erro": str(exc)})
            canal.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return

        extra = {"event_id": envelope.get("event_id"), "tipo": tipo, "correlation_id": envelope.get("correlation_id")}
        if not connection.in_atomic_block:
            close_old_connections()
        try:
            resultado = processar_evento(envelope, handler)
            logger.info("evento_" + resultado, extra=extra)
            canal.basic_ack(delivery_tag=method.delivery_tag)  # ack só depois do commit
        except Exception as exc:  # noqa: BLE001 - qualquer falha do handler vira retry ou DLQ
            tentativas = int((properties.headers or {}).get(CABECALHO_TENTATIVAS, 0)) + 1
            logger.warning("evento_falhou", extra={**extra, "tentativa": tentativas, "erro": repr(exc)})
            if tentativas <= len(filas.retries):
                canal.basic_publish(
                    exchange="",
                    routing_key=filas.retries[tentativas - 1],
                    body=body,
                    properties=pika.BasicProperties(
                        content_type="application/json",
                        delivery_mode=2,
                        message_id=properties.message_id,
                        correlation_id=properties.correlation_id,
                        type=properties.type,
                        headers={**(properties.headers or {}), CABECALHO_TENTATIVAS: tentativas},
                    ),
                )
                canal.basic_ack(delivery_tag=method.delivery_tag)
                return
            falha = getattr(handler, "falha_definitiva", None)
            if falha:
                try:
                    with transaction.atomic():
                        falha(envelope, exc)
                except Exception:  # noqa: BLE001 - a mensagem vai para a DLQ de qualquer jeito
                    logger.exception("falha_definitiva_erro", extra=extra)
            logger.error("evento_enviado_dlq", extra=extra)
            canal.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def executar(self):  # pragma: no cover - laço de I/O, coberto pelo teste de integração
        conn = rabbit.abrir_conexao()
        canal = conn.channel()
        canal.basic_qos(prefetch_count=self.prefetch)
        self.declarar(canal)
        for binding, filas in self.filas.items():
            canal.basic_consume(
                queue=filas.principal,
                on_message_callback=lambda ch, m, p, b, binding=binding: self._on_message(ch, m, p, b, binding),
                auto_ack=False,
            )
            logger.info("consumindo", extra={"fila": filas.principal})
        try:
            canal.start_consuming()
        finally:
            if conn.is_open:
                conn.close()

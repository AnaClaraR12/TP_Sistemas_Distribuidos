"""Consumer base: idempotência, ack após commit, retry com backoff e DLQ.

Os handlers de cada serviço são funções ``handler(envelope: dict) -> None`` registradas
num dicionário ``{binding: handler}`` (binding no formato topic: ``cadastro.#``).
Um handler pode ter o atributo ``falha_definitiva(envelope, exc)`` chamado quando as
tentativas se esgotam (antes de ir para a DLQ).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import pika
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.utils.module_loading import import_string

from tcc_common import request_id_atual
from tcc_common.events import rabbit
from tcc_common.events.models import EventoProcessado

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], None]
CABECALHO_TENTATIVAS = "x-tentativas"


def casar_routing_key(padrao: str, chave: str) -> bool:
    """Casamento no estilo exchange *topic* (``*`` = uma palavra, ``#`` = zero ou mais)."""
    p, c = padrao.split("."), chave.split(".")

    def _casa(i: int, j: int) -> bool:
        if i == len(p):
            return j == len(c)
        if p[i] == "#":
            return any(_casa(i + 1, k) for k in range(j, len(c) + 1))
        if j == len(c):
            return False
        return (p[i] == "*" or p[i] == c[j]) and _casa(i + 1, j + 1)

    return _casa(0, 0)


def encontrar_handler(handlers: dict[str, Handler], tipo: str) -> Handler | None:
    for padrao, handler in handlers.items():
        if casar_routing_key(padrao, tipo):
            return handler
    return None


def processar_evento(envelope: dict[str, Any], handler: Handler) -> str:
    """Executa o handler de forma idempotente, numa transação.

    Retorna ``"processado"`` ou ``"duplicado"``. Exceções do handler propagam
    (a transação é revertida e o evento NÃO é marcado como processado).
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
    """Consome as filas do serviço. Executado por ``manage.py run_consumer``."""

    def __init__(self, servico: str, handlers: dict[str, Handler] | str, prefetch: int = 10) -> None:
        self.servico = servico
        self.handlers: dict[str, Handler] = import_string(handlers) if isinstance(handlers, str) else handlers
        self.prefetch = prefetch
        self.filas: dict[str, rabbit.FilasConsumer] = {}

    def declarar(self, canal) -> None:
        for binding in self.handlers:
            self.filas[binding] = rabbit.declarar_fila_consumer(canal, self.servico, binding)

    def _on_message(self, canal, method, properties, body: bytes, binding: str) -> None:
        filas = self.filas[binding]
        try:
            envelope = json.loads(body)
            handler = encontrar_handler({binding: self.handlers[binding]}, envelope["type"])
            if handler is None:
                raise ValueError(f"Sem handler para {envelope.get('type')}")
        except Exception as exc:  # mensagem malformada: direto para a DLQ
            logger.error("mensagem_invalida", extra={"fila": filas.principal, "erro": str(exc)})
            canal.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return

        extra = {
            "event_id": envelope.get("event_id"),
            "tipo": envelope.get("type"),
            "correlation_id": envelope.get("correlation_id"),
        }
        if not connection.in_atomic_block:  # recicla conexões velhas entre mensagens
            close_old_connections()
        try:
            resultado = processar_evento(envelope, handler)
            logger.info("evento_" + resultado, extra=extra)
            canal.basic_ack(delivery_tag=method.delivery_tag)  # ack só após o commit
        except Exception as exc:  # noqa: BLE001
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
            else:
                falha = getattr(handler, "falha_definitiva", None)
                if falha:
                    try:
                        with transaction.atomic():
                            falha(envelope, exc)
                    except Exception:  # noqa: BLE001
                        logger.exception("falha_definitiva_erro", extra=extra)
                logger.error("evento_enviado_dlq", extra=extra)
                canal.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def executar(self) -> None:  # pragma: no cover - laço de I/O, coberto por teste de integração
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

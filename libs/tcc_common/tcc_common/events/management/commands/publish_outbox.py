"""Publica no RabbitMQ os eventos pendentes da tabela ``outbox``.

Usa ``SELECT ... FOR UPDATE SKIP LOCKED`` para permitir várias réplicas do publisher.
"""

from __future__ import annotations

import logging
import signal
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections, transaction
from django.utils import timezone

from tcc_common.events.models import OutboxEvento
from tcc_common.events.rabbit import Publisher
from tcc_common.events.schemas import CAMPOS_SENSIVEIS

logger = logging.getLogger(__name__)


def mascarar_sensiveis(evento: OutboxEvento) -> None:
    campos = CAMPOS_SENSIVEIS.get(evento.tipo)
    if not campos:
        return
    payload = dict(evento.payload)
    data = dict(payload.get("data", {}))
    for campo in campos:
        if campo in data:
            data[campo] = "***"
    payload["data"] = data
    evento.payload = payload


def publicar_lote(publisher, tamanho: int = 100) -> int:
    """Publica até ``tamanho`` eventos pendentes. Retorna quantos foram publicados."""
    publicados = 0
    with transaction.atomic():
        pendentes = list(
            OutboxEvento.objects.select_for_update(skip_locked=True)
            .filter(publicado_em__isnull=True)
            .order_by("criado_em")[:tamanho]
        )
        for evento in pendentes:
            try:
                publisher.publicar(evento.payload)
            except Exception as exc:  # noqa: BLE001
                evento.tentativas += 1
                evento.ultimo_erro = repr(exc)[:2000]
                evento.save(update_fields=["tentativas", "ultimo_erro"])
                logger.warning("outbox_falha_publicacao", extra={"event_id": str(evento.id), "erro": repr(exc)})
                publisher.fechar()
                break
            evento.publicado_em = timezone.now()
            evento.tentativas += 1
            mascarar_sensiveis(evento)
            evento.save(update_fields=["publicado_em", "tentativas", "payload"])
            publicados += 1
    return publicados


class Command(BaseCommand):
    help = "Publica eventos pendentes do outbox no RabbitMQ (loop)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Publica um lote e sai.")
        parser.add_argument("--intervalo", type=float, default=1.0)

    def handle(self, *args, once=False, intervalo=1.0, **opts):
        publisher = Publisher()
        parar = {"v": False}
        signal.signal(signal.SIGTERM, lambda *_: parar.__setitem__("v", True))
        logger.info("publish_outbox_iniciado")
        while not parar["v"]:
            close_old_connections()
            try:
                n = publicar_lote(publisher)
            except Exception as exc:  # noqa: BLE001
                logger.error("publish_outbox_erro", extra={"erro": repr(exc)})
                publisher.fechar()
                n = 0
            if n:
                logger.info("outbox_publicados", extra={"quantidade": n})
            if once:
                break
            if not n:
                time.sleep(intervalo)
        publisher.fechar()

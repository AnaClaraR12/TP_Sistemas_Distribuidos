"""Inicia o consumer de eventos do serviço (``settings.EVENT_HANDLERS``)."""

import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from tcc_common.events.consumer import BaseConsumer

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Consome eventos do RabbitMQ para este serviço (reconecta automaticamente)."

    def handle(self, *args, **opts):
        consumer = BaseConsumer(
            servico=settings.SERVICO_CURTO,
            handlers=settings.EVENT_HANDLERS,
            prefetch=getattr(settings, "CONSUMER_PREFETCH", 10),
        )
        espera = 1
        while True:
            try:
                consumer.executar()
            except KeyboardInterrupt:
                return
            except Exception as exc:  # noqa: BLE001 - reconexão com backoff
                logger.error("consumer_desconectado", extra={"erro": repr(exc), "nova_tentativa_s": espera})
                time.sleep(espera)
                espera = min(espera * 2, 30)

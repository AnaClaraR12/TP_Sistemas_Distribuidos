"""Declara exchanges e filas do serviço (idempotente) — executado no start."""

from django.conf import settings
from django.core.management.base import BaseCommand

from tcc_common.events import rabbit
from tcc_common.events.consumer import BaseConsumer


class Command(BaseCommand):
    help = "Declara a topologia RabbitMQ (exchanges, filas, retries e DLQ) do serviço."

    def handle(self, *args, **opts):
        conn = rabbit.abrir_conexao()
        canal = conn.channel()
        rabbit.declarar_exchanges(canal)
        handlers = getattr(settings, "EVENT_HANDLERS", None)
        if handlers:
            consumer = BaseConsumer(settings.SERVICO_CURTO, handlers)
            consumer.declarar(canal)
            for f in consumer.filas.values():
                self.stdout.write(f"fila declarada: {f.principal} (+{len(f.retries)} retries, dlq)")
        conn.close()
        self.stdout.write(self.style.SUCCESS("Topologia declarada."))

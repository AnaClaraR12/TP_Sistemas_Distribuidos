"""Verifica o SHA-256 de todas as monografias com arquivo aprovado (rodar diariamente)."""

from django.core.management.base import BaseCommand

from apps.monografias.models import Monografia
from apps.monografias.servicos import verificar_integridade


class Command(BaseCommand):
    help = "Recalcula o SHA-256 dos arquivos aprovados e alerta divergências."

    def handle(self, *args, **opts):
        total = violadas = 0
        for m in Monografia.objects.filter(arquivo_sha256_aprovado__isnull=False).iterator():
            total += 1
            if not verificar_integridade(m)["integridade_ok"]:
                violadas += 1
                self.stderr.write(f"INTEGRIDADE VIOLADA: {m.id} — {m.titulo}")
        self.stdout.write(self.style.SUCCESS(f"{total} verificadas, {violadas} com divergência."))

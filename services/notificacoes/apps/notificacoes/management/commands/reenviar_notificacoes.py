"""Reenvia notificações que falharam (ex.: SMTP fora por muito tempo)."""

from django.core.management.base import BaseCommand

from apps.notificacoes.envio import _enviar_com_retry
from apps.notificacoes.models import Notificacao


class Command(BaseCommand):
    help = "Tenta reenviar notificações com status 'falhou' (sem segredos: usa o corpo armazenado)."

    def handle(self, *args, **opts):
        ok = 0
        for n in Notificacao.objects.filter(status=Notificacao.Status.FALHOU):
            _enviar_com_retry(n, n.corpo)
            n.save()
            ok += n.status == Notificacao.Status.ENVIADA
        self.stdout.write(self.style.SUCCESS(f"{ok} notificações reenviadas."))

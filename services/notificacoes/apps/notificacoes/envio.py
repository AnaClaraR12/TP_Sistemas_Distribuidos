"""Envio idempotente com retry/backoff."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.notificacoes.models import Notificacao
from apps.notificacoes.templates_email import renderizar

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Destinatario:
    email: str
    nome: str = ""
    id: str | None = None


def _enviar_com_retry(notif: Notificacao, corpo_real: str) -> None:
    for tentativa in range(1, settings.NOTIFICACAO_TENTATIVAS + 1):
        notif.tentativas += 1
        try:
            send_mail(notif.assunto, corpo_real, None, [notif.destinatario_email], fail_silently=False)
            notif.status = Notificacao.Status.ENVIADA
            notif.enviada_em = timezone.now()
            notif.ultimo_erro = ""
            return
        except Exception as exc:  # noqa: BLE001 - SMTP pode falhar de muitas formas
            notif.ultimo_erro = repr(exc)[:1000]
            logger.warning("falha_envio_email", extra={"tentativa": tentativa, "tipo": notif.tipo, "erro": repr(exc)})
            if tentativa < settings.NOTIFICACAO_TENTATIVAS:
                time.sleep(settings.NOTIFICACAO_BACKOFF_S * (2 ** (tentativa - 1)))
    notif.status = Notificacao.Status.FALHOU


def notificar(
    envelope: dict, tipo: str, destinatarios: list[Destinatario], contexto: dict, segredos: tuple[str, ...] = ()
) -> list[Notificacao]:
    """Uma notificação por destinatário, idempotente por (evento, e-mail, tipo)."""
    vistos: set[str] = set()
    resultado = []
    for d in destinatarios:
        email = (d.email or "").strip().lower()
        if not email or email in vistos:
            continue
        vistos.add(email)
        existente = Notificacao.objects.filter(
            evento_origem=envelope["event_id"], destinatario_email=email, tipo=tipo
        ).first()
        if existente and existente.status == Notificacao.Status.ENVIADA:
            resultado.append(existente)
            continue
        ctx = {**contexto, "nome": d.nome or email, "frontend": settings.FRONTEND_URL.rstrip("/")}
        assunto, corpo_real = renderizar(tipo, ctx)
        corpo_salvo = corpo_real
        for s in segredos:
            if s:
                corpo_salvo = corpo_salvo.replace(s, "***")
        notif = existente or Notificacao(
            evento_origem=envelope["event_id"],
            destinatario_email=email,
            destinatario_id=d.id,
            tipo=tipo,
            assunto=assunto,
            corpo=corpo_salvo,
        )
        _enviar_com_retry(notif, corpo_real)
        try:
            with transaction.atomic():
                notif.save()
        except IntegrityError:  # outro worker gravou a mesma notificação
            continue
        resultado.append(notif)
    return resultado

"""Sinais: auditoria de login/logout/falha, contador de bloqueio e grupos por papel."""

from __future__ import annotations

from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.contas.backends import limpar_falhas, registrar_falha
from apps.contas.models import GRUPO_POR_PAPEL, User
from tcc_common.audit.auditoria import registrar_auditoria
from tcc_common.middleware.rede_institucional import ip_do_cliente


@receiver(user_logged_in)
def ao_logar(sender, request, user, **kwargs):
    limpar_falhas(user.email)
    if request is not None:
        User.objects.filter(pk=user.pk).update(ultimo_login_ip=ip_do_cliente(request))
    registrar_auditoria("login", "usuario", user.pk, request=request, usuario=user)


@receiver(user_login_failed)
def ao_falhar_login(sender, credentials, request=None, **kwargs):
    email = (credentials.get("email") or credentials.get("username") or credentials.get("login") or "").lower()
    total = registrar_falha(email) if email else 0
    registrar_auditoria(
        "login_falhou",
        "usuario",
        None,
        request=request,
        usuario=None,
        detalhes={"email": email, "tentativas": total},
    )


@receiver(user_logged_out)
def ao_deslogar(sender, request, user, **kwargs):
    if user is not None:
        registrar_auditoria("logout", "usuario", user.pk, request=request, usuario=user)


@receiver(post_save, sender=User)
def sincronizar_grupo(sender, instance: User, **kwargs):
    """Mantém o usuário no grupo Django correspondente ao seu papel."""
    nome = GRUPO_POR_PAPEL.get(instance.papel)
    if not nome:
        return
    grupo = Group.objects.filter(name=nome).first()
    if grupo and not instance.groups.filter(pk=grupo.pk).exists():
        instance.groups.set([grupo])

"""Regras do diretório acadêmico: criação de usuário vinculado, papéis e eventos cadastro.*."""

from __future__ import annotations

import logging

from allauth.account.forms import default_token_generator
from allauth.account.utils import user_pk_to_url_str
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse

from apps.academico.models import Aluno, Curso, Professor
from apps.contas.models import Papel
from tcc_common.api.exceptions import ErroNegocio
from tcc_common.events.outbox import registrar_evento

logger = logging.getLogger(__name__)
User = get_user_model()


def criar_usuario_vinculado(email: str, nome: str, papel: str):
    """Cria o ``User`` com senha inutilizável e agenda o e-mail "defina sua senha"."""
    email = email.lower()
    if User.objects.filter(email=email).exists():
        raise ErroNegocio("Já existe um usuário com este e-mail.", codigo="email_em_uso", status_code=409)
    user = User.objects.create_user(email=email, password=None, nome=nome, papel=papel)
    transaction.on_commit(lambda: enviar_email_definir_senha(user))
    return user


def enviar_email_definir_senha(user) -> None:
    caminho = reverse(
        "account_reset_password_from_key",
        kwargs={"uidb36": user_pk_to_url_str(user), "key": default_token_generator.make_token(user)},
    )
    link = settings.FRONTEND_URL.rstrip("/") + caminho
    try:
        send_mail(
            "[TCC] Defina sua senha de acesso",
            f"Olá, {user.nome or user.email}!\n\nSua conta no Sistema de Monografias foi criada.\n"
            f"Defina sua senha em: {link}\n\nSe você não esperava este e-mail, ignore-o.",
            None,
            [user.email],
        )
    except Exception as exc:  # noqa: BLE001 - e-mail não pode quebrar o cadastro
        logger.warning("falha_email_definir_senha", extra={"erro": repr(exc)})


def sincronizar_papel_coordenador(professor: Professor | None) -> None:
    """Professor que coordena algum curso tem papel ``coordenador``; senão ``professor``."""
    if professor is None or professor.user.papel == Papel.ADMIN:
        return
    novo = Papel.COORDENADOR if professor.cursos_coordenados.exists() else Papel.PROFESSOR
    if professor.user.papel != novo:
        professor.user.papel = novo
        professor.user.save(update_fields=["papel", "is_staff"])


# --- eventos cadastro.* -------------------------------------------------------------


def publicar_curso(curso: Curso) -> None:
    registrar_evento(
        "cadastro.curso.upserted",
        {
            "id": curso.id,
            "nome": curso.nome,
            "codigo": curso.codigo,
            "coordenador_id": curso.coordenador_id,
        },
    )


def publicar_professor(p: Professor) -> None:
    registrar_evento(
        "cadastro.professor.upserted",
        {
            "id": p.id,
            "nome": p.nome,
            "email": p.email,
            "departamento": p.departamento,
            "area_pesquisa": p.area_pesquisa,
            "papel": p.user.papel,
        },
    )


def publicar_aluno(a: Aluno) -> None:
    registrar_evento(
        "cadastro.aluno.upserted",
        {
            "id": a.id,
            "nome": a.nome,
            "email": a.email,
            "matricula": a.matricula,
            "curso_id": a.curso_id,
            "orientador_id": a.orientador_atual_id,
        },
    )


def publicar_exclusao(tipo: str, pk) -> None:
    registrar_evento(f"cadastro.{tipo}.deleted", {"id": pk})

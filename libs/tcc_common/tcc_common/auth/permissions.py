"""Permissões DRF reutilizáveis (matriz do Anexo D)."""

from __future__ import annotations

import hmac

from django.conf import settings
from rest_framework.permissions import SAFE_METHODS, BasePermission


def _papel(request) -> str | None:
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return None
    return getattr(user, "papel", None)


class _PorPapel(BasePermission):
    papeis: tuple[str, ...] = ()
    message = "Seu papel não permite esta ação."

    def has_permission(self, request, view) -> bool:
        return _papel(request) in self.papeis


class IsAutenticado(BasePermission):
    message = "Autenticação necessária."

    def has_permission(self, request, view) -> bool:
        return _papel(request) is not None


class IsAdmin(_PorPapel):
    papeis = ("admin",)


class IsCoordenador(_PorPapel):
    """Coordenador ou admin."""

    papeis = ("coordenador", "admin")


class IsProfessor(_PorPapel):
    """Professor, coordenador (também é professor) ou admin."""

    papeis = ("professor", "coordenador", "admin")


class IsAluno(_PorPapel):
    papeis = ("aluno", "admin")


def papeis(*permitidos: str) -> type[BasePermission]:
    """Fábrica: ``permission_classes = [papeis("aluno", "admin")]``."""
    return type(f"Papeis_{'_'.join(permitidos)}", (_PorPapel,), {"papeis": permitidos})


class IsDonoOuOrientador(BasePermission):
    """Objeto com ``aluno_id``/``orientador_id``: dono, orientador, coordenador do curso ou admin."""

    message = "Você não tem acesso a este recurso."

    def has_object_permission(self, request, view, obj) -> bool:
        u = request.user
        if u.papel == "admin":
            return True
        if u.aluno_id and str(getattr(obj, "aluno_id", "")) == str(u.aluno_id):
            return True
        if u.professor_id and str(getattr(obj, "orientador_id", "")) == str(u.professor_id):
            return True
        if u.papel == "coordenador" and str(getattr(obj, "curso_id", "")) in {str(c) for c in u.curso_ids}:
            return True
        return False


class ReadOnlyOrPublic(BasePermission):
    """Leitura liberada a qualquer visitante; escrita bloqueada."""

    def has_permission(self, request, view) -> bool:
        return request.method in SAFE_METHODS


class IsServicoInterno(BasePermission):
    """Chamada serviço-a-serviço com ``X-Service-Token`` (segredo compartilhado)."""

    message = "Token de serviço inválido."

    def has_permission(self, request, view) -> bool:
        recebido = request.headers.get("X-Service-Token", "")
        esperado = getattr(settings, "SERVICE_TOKEN", "")
        return bool(esperado) and hmac.compare_digest(recebido, esperado)

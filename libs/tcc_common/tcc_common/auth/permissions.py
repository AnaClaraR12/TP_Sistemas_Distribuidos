import hmac

from django.conf import settings
from rest_framework.permissions import BasePermission


def _papel(request):
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return None
    return getattr(user, "papel", None)


class _PorPapel(BasePermission):
    papeis = ()
    message = "Seu papel não permite esta ação."

    def has_permission(self, request, view):
        return _papel(request) in self.papeis


class IsAutenticado(BasePermission):
    message = "Autenticação necessária."

    def has_permission(self, request, view):
        return _papel(request) is not None


class IsAdmin(_PorPapel):
    papeis = ("admin",)


class IsCoordenador(_PorPapel):
    papeis = ("coordenador", "admin")


def papeis(*permitidos):
    """``permission_classes = [papeis("aluno", "admin")]``"""
    return type(f"Papeis_{'_'.join(permitidos)}", (_PorPapel,), {"papeis": permitidos})


class IsServicoInterno(BasePermission):
    """Chamada entre serviços, autenticada pelo segredo compartilhado ``X-Service-Token``."""

    message = "Token de serviço inválido."

    def has_permission(self, request, view):
        recebido = request.headers.get("X-Service-Token", "")
        esperado = getattr(settings, "SERVICE_TOKEN", "")
        # sem SERVICE_TOKEN configurado, ninguém passa (nem quem manda o cabeçalho vazio)
        return bool(esperado) and hmac.compare_digest(recebido, esperado)

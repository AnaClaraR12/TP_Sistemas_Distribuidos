"""Bloqueio por tentativas: 5 falhas em 15 min -> bloqueio (Redis ``login_falhas:<email>``)."""

from django.conf import settings
from django.core.exceptions import PermissionDenied

from tcc_common.cache.redis import get_redis

PREFIXO = "login_falhas:"


def _chave(email: str) -> str:
    return PREFIXO + (email or "").strip().lower()


def esta_bloqueado(email: str) -> bool:
    valor = get_redis().get(_chave(email))
    return int(valor or 0) >= settings.LOGIN_MAX_FALHAS


def registrar_falha(email: str) -> int:
    r = get_redis()
    chave = _chave(email)
    total = r.incr(chave)
    r.expire(chave, settings.LOGIN_JANELA_S, nx=True)
    return int(total)


def limpar_falhas(email: str) -> None:
    get_redis().delete(_chave(email))


def tempo_restante(email: str) -> int:
    return max(int(get_redis().ttl(_chave(email))), 0)


class BloqueioPorTentativasBackend:
    """Primeiro backend da cadeia: interrompe a autenticação de contas bloqueadas."""

    def authenticate(self, request, email=None, username=None, password=None, **kwargs):
        identificador = email or username or kwargs.get("login")
        if identificador and esta_bloqueado(identificador):
            raise PermissionDenied("Conta temporariamente bloqueada por excesso de tentativas.")
        return None

    def get_user(self, user_id):
        return None

"""Biblioteca compartilhada (auth JWT, eventos, cache, auditoria, middleware) dos microsserviços."""

from contextvars import ContextVar

__version__ = "1.0.0"

#: request_id da requisição/evento corrente (propagado via X-Request-ID / correlation_id)
request_id_atual: ContextVar[str | None] = ContextVar("request_id_atual", default=None)

#: usuário autenticado corrente (UsuarioToken) — usado pelo histórico e pela auditoria
usuario_atual: ContextVar[object | None] = ContextVar("usuario_atual", default=None)

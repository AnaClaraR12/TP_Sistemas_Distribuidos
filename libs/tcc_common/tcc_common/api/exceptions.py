"""Erros de negócio e exception handler padrão: {"codigo", "mensagem", "detalhes"}."""

import logging
from typing import Any

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class ErroNegocio(exceptions.APIException):
    """Erro de regra de negócio com código estável para o cliente."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "erro_negocio"
    default_detail = "Operação não permitida no estado atual."

    def __init__(
        self,
        mensagem: str | None = None,
        codigo: str | None = None,
        status_code: int | None = None,
        detalhes: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(mensagem or self.default_detail, codigo or self.default_code)
        self.codigo = codigo or self.default_code
        self.mensagem = mensagem or str(self.default_detail)
        self.detalhes = detalhes or {}
        self.headers = headers or {}
        if status_code:
            self.status_code = status_code


_CODIGOS_PADRAO = {
    400: "requisicao_invalida",
    401: "nao_autenticado",
    403: "acesso_negado",
    404: "nao_encontrado",
    405: "metodo_nao_permitido",
    409: "conflito",
    413: "arquivo_muito_grande",
    415: "tipo_nao_suportado",
    429: "limite_de_requisicoes",
}

_MENSAGENS_PADRAO = {
    400: "Dados inválidos.",
    401: "Autenticação necessária ou token inválido.",
    403: "Você não tem permissão para executar esta ação.",
    404: "Recurso não encontrado.",
    405: "Método não permitido.",
    429: "Muitas requisições. Tente novamente mais tarde.",
}


def exception_handler(exc: Exception, context: dict) -> Response | None:
    """Converte qualquer erro da API para o formato JSON padrão do projeto."""
    if isinstance(exc, ErroNegocio):
        resp = Response(
            {"codigo": exc.codigo, "mensagem": exc.mensagem, "detalhes": exc.detalhes},
            status=exc.status_code,
        )
        for k, v in exc.headers.items():
            resp[k] = v
        return resp

    if isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(detail=exc.message_dict if hasattr(exc, "message_dict") else exc.messages)
    elif isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, PermissionDenied):
        exc = exceptions.PermissionDenied()

    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("erro_nao_tratado", exc_info=exc)
        return Response(
            {"codigo": "erro_interno", "mensagem": "Erro interno do servidor.", "detalhes": {}},
            status=500,
        )

    codigo = _CODIGOS_PADRAO.get(response.status_code, "erro")
    if isinstance(exc, exceptions.APIException):
        codes = exc.get_codes()
        if isinstance(codes, str) and codes not in ("invalid", "error"):
            codigo = codes if response.status_code != 400 else codigo
    data = response.data
    if isinstance(exc, exceptions.ValidationError):
        mensagem = _MENSAGENS_PADRAO[400]
        detalhes = data if isinstance(data, dict) else {"erros": data}
    else:
        mensagem = (
            data.get("detail", _MENSAGENS_PADRAO.get(response.status_code, "Erro."))
            if isinstance(data, dict)
            else str(data)
        )
        detalhes = {}
        if isinstance(exc, exceptions.Throttled) and exc.wait:
            detalhes = {"retry_after": int(exc.wait)}
    response.data = {"codigo": codigo, "mensagem": str(mensagem), "detalhes": detalhes}
    return response

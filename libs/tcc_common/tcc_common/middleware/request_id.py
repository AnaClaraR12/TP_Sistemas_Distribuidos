"""Propaga o X-Request-ID (gerado pelo gateway) para logs, eventos e resposta."""

from __future__ import annotations

import re
import uuid

from tcc_common import request_id_atual, usuario_atual

_VALIDO = re.compile(r"^[A-Za-z0-9\-_.]{8,128}$")


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        rid = request.headers.get("X-Request-ID", "")
        if not _VALIDO.match(rid):
            rid = uuid.uuid4().hex
        request.request_id = rid
        t1 = request_id_atual.set(rid)
        t2 = usuario_atual.set(None)
        try:
            response = self.get_response(request)
        finally:
            request_id_atual.reset(t1)
            usuario_atual.reset(t2)
        response["X-Request-ID"] = rid
        return response

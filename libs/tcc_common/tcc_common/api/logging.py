"""Formatter de log estruturado em JSON com request_id e user_id."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from tcc_common import request_id_atual, usuario_atual

_CAMPOS_PADRAO = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}
_CHAVES_SENSIVEIS = {"token", "password", "senha", "authorization", "access", "refresh"}


class JsonFormatter(logging.Formatter):
    def __init__(self, servico: str = "?", *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.servico = servico

    def format(self, record: logging.LogRecord) -> str:
        usuario = usuario_atual.get()
        dados = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "nivel": record.levelname,
            "logger": record.name,
            "servico": self.servico,
            "mensagem": record.getMessage(),
            "request_id": request_id_atual.get(),
            "user_id": str(getattr(usuario, "id", "")) or None,
        }
        for chave, valor in record.__dict__.items():
            if chave in _CAMPOS_PADRAO or chave.startswith("_"):
                continue
            dados[chave] = "***" if chave.lower() in _CHAVES_SENSIVEIS else valor
        if record.exc_info:
            dados["exc"] = self.formatException(record.exc_info)
        return json.dumps(dados, default=str, ensure_ascii=False)

"""Envelope padrão e gravação no outbox (mesma transação do dado de negócio)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder

from tcc_common import request_id_atual, usuario_atual
from tcc_common.events.schemas import SCHEMA_VERSION, validar_dados


def _json_seguro(data: dict[str, Any]) -> dict[str, Any]:
    """Converte UUID/datetime/Decimal em tipos JSON."""
    return json.loads(json.dumps(data, cls=DjangoJSONEncoder))


def criar_envelope(
    tipo: str,
    data: dict[str, Any],
    *,
    actor_id: str | None = None,
    correlation_id: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Monta o envelope padrão (seção Fase 3, item 2) e valida o schema do tipo."""
    data = _json_seguro(data)
    validar_dados(tipo, data)
    if actor_id is None:
        usuario = usuario_atual.get()
        actor_id = getattr(usuario, "id", None)
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "type": tipo,
        "schema_version": SCHEMA_VERSION,
        "occurred_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "producer": getattr(settings, "SERVICO_NOME", "desconhecido"),
        "correlation_id": correlation_id or request_id_atual.get(),
        "actor_id": str(actor_id) if actor_id else None,
        "data": data,
    }


def registrar_evento(tipo: str, data: dict[str, Any], **kwargs) -> OutboxEvento:  # noqa: F821
    """Grava o evento na tabela ``outbox``. Deve ser chamado dentro da transação do dado."""
    from tcc_common.events.models import OutboxEvento

    envelope = criar_envelope(tipo, data, **kwargs)
    return OutboxEvento.objects.create(id=envelope["event_id"], tipo=tipo, payload=envelope)

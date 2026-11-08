"""Gravação de registros de auditoria (local e vindos de outros serviços)."""

from __future__ import annotations

import ipaddress
import uuid
from typing import Any

from apps.auditoria.models import RegistroAuditoria


def _uuid_ou_none(valor: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(valor)) if valor else None
    except ValueError:
        return None


def _ip_ou_none(valor: Any) -> str | None:
    try:
        return str(ipaddress.ip_address(valor)) if valor else None
    except ValueError:
        return None


def gravar_registro(dados: dict[str, Any]) -> RegistroAuditoria:
    """Persiste um registro no formato do evento ``audit.registro``."""
    return RegistroAuditoria.objects.create(
        usuario_id=_uuid_ou_none(dados.get("usuario_id")),
        usuario_email=dados.get("usuario_email") or "",
        papel=dados.get("papel") or "",
        acao=dados["acao"][:80],
        recurso=(dados.get("recurso") or "")[:80],
        recurso_id=str(dados.get("recurso_id") or "")[:64],
        ip=_ip_ou_none(dados.get("ip")),
        user_agent=(dados.get("user_agent") or "")[:300],
        servico_origem=dados.get("servico_origem") or "auth-service",
        nivel=dados.get("nivel") if dados.get("nivel") in ("info", "critico") else "info",
        detalhes=dados.get("detalhes") or {},
    )

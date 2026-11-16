"""Histórico de alterações (django-simple-history) com usuário vindo do JWT.

Nos serviços não existe tabela de usuários: guardamos ``history_user_id`` (UUID) do
usuário autenticado no momento da alteração (``usuario_atual``) — quem / o quê / quando.
"""

from typing import Any

from django.db import models
from rest_framework.decorators import action
from rest_framework.response import Response
from simple_history.models import HistoricalRecords

from tcc_common import usuario_atual


def _obter_usuario(instance=None, request=None, **kwargs):
    usuario = getattr(instance, "_history_user", None) if instance is not None else None
    return usuario or usuario_atual.get()


def _setter(historical_instance, user) -> None:
    if user is not None:
        historical_instance.history_user_id = getattr(user, "id", None) or getattr(user, "pk", None)


def _getter(historical_instance):
    return historical_instance.history_user_id


def Historico(**kwargs) -> HistoricalRecords:  # noqa: N802 - fábrica com cara de classe
    """``HistoricalRecords`` configurado para guardar o UUID do usuário do JWT."""
    return HistoricalRecords(
        history_user_id_field=models.UUIDField(null=True, blank=True),
        history_user_getter=_getter,
        history_user_setter=_setter,
        get_user=_obter_usuario,
        **kwargs,
    )


def _serializavel(valor: Any) -> Any:
    if valor is None or isinstance(valor, (str, int, float, bool)):
        return valor
    if isinstance(valor, (list, tuple)):
        return [_serializavel(v) for v in valor]
    if hasattr(valor, "name") and hasattr(valor, "url"):  # FieldFile
        return valor.name or None
    return str(valor)


_TIPOS = {"+": "criacao", "~": "alteracao", "-": "exclusao"}


def diff_historico(objeto, ignorar: set[str] | None = None) -> list[dict[str, Any]]:
    """Lista as versões do objeto com o diff campo a campo (mais recente primeiro)."""
    ignorar = (ignorar or set()) | {"atualizado_em"}
    registros = list(objeto.history.all().order_by("history_date", "history_id"))
    saida: list[dict[str, Any]] = []
    anterior = None
    for reg in registros:
        alteracoes = []
        if anterior is not None:
            delta = reg.diff_against(anterior)
            for ch in delta.changes:
                if ch.field in ignorar:
                    continue
                alteracoes.append({"campo": ch.field, "anterior": _serializavel(ch.old), "novo": _serializavel(ch.new)})
        saida.append(
            {
                "versao": reg.history_id,
                "tipo": _TIPOS.get(reg.history_type, reg.history_type),
                "usuario_id": str(reg.history_user_id) if reg.history_user_id else None,
                "data_hora": reg.history_date.isoformat(),
                "motivo": reg.history_change_reason,
                "alteracoes": alteracoes,
            }
        )
        anterior = reg
    return list(reversed(saida))


class HistoricoMixin:
    """Adiciona ``GET /<recurso>/{id}/historico/`` a um ViewSet."""

    @action(detail=True, methods=["get"], url_path="historico")
    def historico(self, request, *args, **kwargs):
        objeto = self.get_object()
        return Response({"id": str(objeto.pk), "historico": diff_historico(objeto)})

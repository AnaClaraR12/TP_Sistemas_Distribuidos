"""Registro de auditoria de ações.

Cada serviço publica ``audit.registro`` (via outbox); o auth-service consome e centraliza
em ``RegistroAuditoria``. No próprio auth-service, ``AUDITORIA_HANDLER_LOCAL`` grava direto.
"""

from typing import Any

from django.conf import settings
from django.utils.module_loading import import_string

from tcc_common import usuario_atual


def registrar_auditoria(
    acao: str,
    recurso: str,
    recurso_id: Any = None,
    *,
    request=None,
    usuario=None,
    detalhes: dict[str, Any] | None = None,
    nivel: str = "info",
) -> None:
    """Registra quem fez o quê, em qual recurso, quando e de onde."""
    from tcc_common.middleware.rede_institucional import ip_do_cliente

    usuario = usuario or usuario_atual.get()
    dados = {
        "usuario_id": str(getattr(usuario, "id", "") or "") or None,
        "usuario_email": getattr(usuario, "email", None),
        "papel": getattr(usuario, "papel", None),
        "acao": acao,
        "recurso": recurso,
        "recurso_id": str(recurso_id) if recurso_id is not None else None,
        "ip": ip_do_cliente(request) if request is not None else None,
        "user_agent": (request.headers.get("User-Agent", "")[:300] if request is not None else None),
        "servico_origem": getattr(settings, "SERVICO_NOME", "?"),
        "nivel": nivel,
        "detalhes": detalhes or {},
    }
    local = getattr(settings, "AUDITORIA_HANDLER_LOCAL", None)
    if local:
        import_string(local)(dados)
        return
    from tcc_common.events.outbox import registrar_evento

    registrar_evento("audit.registro", dados, actor_id=dados["usuario_id"])


class AuditoriaViewSetMixin:
    """Audita create/update/destroy de ViewSets DRF."""

    auditoria_recurso: str = ""

    def _auditar(self, acao: str, instancia, detalhes: dict | None = None) -> None:
        registrar_auditoria(
            acao,
            self.auditoria_recurso or instancia.__class__.__name__.lower(),
            getattr(instancia, "pk", None),
            request=self.request,
            usuario=self.request.user,
            detalhes=detalhes,
        )

    def perform_create(self, serializer):
        super().perform_create(serializer)
        self._auditar("criacao", serializer.instance)

    def perform_update(self, serializer):
        super().perform_update(serializer)
        self._auditar("alteracao", serializer.instance, {"campos": sorted(serializer.validated_data.keys())})

    def perform_destroy(self, instance):
        pk = instance.pk
        super().perform_destroy(instance)
        instance.pk = pk
        self._auditar("exclusao", instance)

"""Tabelas ``outbox`` e ``evento_processado`` — criadas no banco de CADA serviço."""

import uuid

from django.db import models


class OutboxEvento(models.Model):
    """Evento gravado na mesma transação do dado de negócio (Transactional Outbox)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # == event_id
    tipo = models.CharField(max_length=100, db_index=True)
    payload = models.JSONField()
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    publicado_em = models.DateTimeField(null=True, blank=True, db_index=True)
    tentativas = models.PositiveIntegerField(default=0)
    ultimo_erro = models.TextField(blank=True, default="")

    class Meta:
        db_table = "outbox"
        ordering = ["criado_em"]
        indexes = [models.Index(fields=["publicado_em", "criado_em"], name="outbox_pendentes_idx")]

    def __str__(self) -> str:
        return f"{self.tipo} ({self.id})"


class EventoProcessado(models.Model):
    """Registro de idempotência dos consumers (``event_id`` único)."""

    event_id = models.UUIDField(unique=True)
    tipo = models.CharField(max_length=100)
    processado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "evento_processado"

    def __str__(self) -> str:
        return f"{self.tipo} ({self.event_id})"

import uuid

from django.db import models


class RegistroAuditoria(models.Model):
    class Nivel(models.TextChoices):
        INFO = "info", "Informativo"
        CRITICO = "critico", "Crítico"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usuario_id = models.UUIDField(null=True, blank=True)
    usuario_email = models.CharField(max_length=254, blank=True, default="")
    papel = models.CharField(max_length=20, blank=True, default="")
    acao = models.CharField(max_length=80)
    recurso = models.CharField(max_length=80)
    recurso_id = models.CharField(max_length=64, blank=True, default="")
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True, default="")
    servico_origem = models.CharField(max_length=50, default="auth-service")
    nivel = models.CharField(max_length=10, choices=Nivel.choices, default=Nivel.INFO)
    detalhes = models.JSONField(default=dict, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "registro de auditoria"
        verbose_name_plural = "registros de auditoria"
        indexes = [
            models.Index(fields=["criado_em"], name="audit_criado_idx"),
            models.Index(fields=["usuario_id"], name="audit_usuario_idx"),
            models.Index(fields=["recurso", "recurso_id"], name="audit_recurso_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.criado_em:%Y-%m-%d %H:%M} {self.acao} {self.recurso}"

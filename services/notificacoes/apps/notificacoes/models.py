import uuid

from django.db import models


class Notificacao(models.Model):
    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        ENVIADA = "enviada", "Enviada"
        FALHOU = "falhou", "Falhou"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    destinatario_email = models.EmailField(db_index=True)
    destinatario_id = models.UUIDField(null=True, blank=True)
    tipo = models.CharField(max_length=60)
    assunto = models.CharField(max_length=200)
    #: corpo armazenado SEM segredos (token mascarado)
    corpo = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDENTE)
    tentativas = models.PositiveIntegerField(default=0)
    ultimo_erro = models.TextField(blank=True, default="")
    evento_origem = models.UUIDField()
    criada_em = models.DateTimeField(auto_now_add=True)
    enviada_em = models.DateTimeField(null=True, blank=True)
    lida_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-criada_em"]
        constraints = [
            models.UniqueConstraint(
                fields=["evento_origem", "destinatario_email", "tipo"], name="notificacao_idempotente"
            )
        ]


class AlunoRef(models.Model):
    id = models.UUIDField(primary_key=True)
    nome = models.CharField(max_length=150)
    email = models.EmailField()
    curso_id = models.UUIDField(null=True)


class ProfessorRef(models.Model):
    id = models.UUIDField(primary_key=True)
    nome = models.CharField(max_length=150)
    email = models.EmailField()


class CursoRef(models.Model):
    id = models.UUIDField(primary_key=True)
    nome = models.CharField(max_length=150)
    coordenador_id = models.UUIDField(null=True)

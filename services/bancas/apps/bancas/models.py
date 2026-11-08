"""Banca, MembroBanca, Avaliacao e read models (MonografiaRef, ProfessorRef)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.core.validators import MaxValueValidator, MinLengthValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from tcc_common.audit.historico import Historico


class Base(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class MonografiaRef(models.Model):
    """Cópia de leitura alimentada por eventos ``monografia.*``."""

    id = models.UUIDField(primary_key=True)
    titulo = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=20, blank=True)
    aprovacao_orientador = models.CharField(max_length=20, blank=True)
    aluno_id = models.UUIDField(null=True)
    orientador_id = models.UUIDField(null=True)
    curso_id = models.UUIDField(null=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    @property
    def apta_para_banca(self) -> bool:
        return self.status == "em_avaliacao" and self.aprovacao_orientador == "aprovada"


class ProfessorRef(models.Model):
    id = models.UUIDField(primary_key=True)
    nome = models.CharField(max_length=150)
    email = models.EmailField()
    departamento = models.CharField(max_length=150, blank=True)


class Banca(Base):
    class Status(models.TextChoices):
        EM_ORGANIZACAO = "em_organizacao", "Em organização"
        AGENDADA = "agendada", "Agendada"
        REALIZADA = "realizada", "Realizada"
        CANCELADA = "cancelada", "Cancelada"

    monografia_id = models.UUIDField(db_index=True)
    data_hora_inicio = models.DateTimeField()
    duracao_minutos = models.PositiveIntegerField(
        default=120, validators=[MinValueValidator(15), MaxValueValidator(600)]
    )
    local = models.CharField(max_length=200, null=True, blank=True)
    link = models.URLField(max_length=500, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.EM_ORGANIZACAO, db_index=True)
    resultado_final = models.CharField(
        max_length=20, null=True, blank=True, choices=[("aprovada", "Aprovada"), ("reprovada", "Reprovada")]
    )
    media_final = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    exige_correcao = models.BooleanField(default=False)
    resultado_calculado_em = models.DateTimeField(null=True, blank=True)
    criada_por_id = models.UUIDField(null=True, blank=True)
    motivo_cancelamento = models.TextField(blank=True, default="")

    history = Historico()

    class Meta:
        ordering = ["-data_hora_inicio"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(local__isnull=False) & Q(link__isnull=True))
                | (Q(local__isnull=True) & Q(link__isnull=False)),
                name="banca_local_xor_link",
            )
        ]

    @property
    def data_hora_fim(self):
        return self.data_hora_inicio + timedelta(minutes=self.duracao_minutos)

    def __str__(self) -> str:
        return f"Banca {self.id} ({self.status})"


class MembroBanca(Base):
    class Tipo(models.TextChoices):
        INTERNO = "interno", "Interno"
        EXTERNO = "externo", "Externo"

    class Funcao(models.TextChoices):
        ORIENTADOR = "orientador", "Orientador"
        MEMBRO = "membro", "Membro"
        PRESIDENTE = "presidente", "Presidente"

    class Confirmacao(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        CONFIRMADO = "confirmado", "Confirmado"
        RECUSADO = "recusado", "Recusado"

    banca = models.ForeignKey(Banca, on_delete=models.CASCADE, related_name="membros")
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    professor_id = models.UUIDField(null=True, blank=True, db_index=True)
    nome = models.CharField(max_length=150)
    email = models.EmailField(db_index=True)
    instituicao = models.CharField(max_length=200, null=True, blank=True)
    funcao = models.CharField(max_length=20, choices=Funcao.choices, default=Funcao.MEMBRO)
    confirmacao = models.CharField(max_length=20, choices=Confirmacao.choices, default=Confirmacao.PENDENTE)
    confirmado_em = models.DateTimeField(null=True, blank=True)
    #: SHA-256 do token do membro externo (o token em claro nunca é persistido)
    token_hash = models.CharField(max_length=64, null=True, blank=True, unique=True)
    token_expira_em = models.DateTimeField(null=True, blank=True)
    token_revogado = models.BooleanField(default=False)

    history = Historico(excluded_fields=["token_hash"])

    class Meta:
        ordering = ["funcao", "nome"]
        constraints = [models.UniqueConstraint(fields=["banca", "email"], name="membro_unico_por_banca")]

    def __str__(self) -> str:
        return f"{self.nome} ({self.tipo})"


class Avaliacao(Base):
    class Recomendacao(models.TextChoices):
        SEM_RESSALVAS = "aprovado_sem_ressalvas", "Aprovado sem ressalvas"
        COM_RESSALVAS = "aprovado_com_ressalvas", "Aprovado com ressalvas"
        REPROVADO = "reprovado", "Reprovado"

    banca = models.ForeignKey(Banca, on_delete=models.CASCADE, related_name="avaliacoes")
    membro = models.ForeignKey(MembroBanca, on_delete=models.CASCADE, related_name="avaliacoes")
    nota = models.DecimalField(max_digits=3, decimal_places=1, validators=[MinValueValidator(0), MaxValueValidator(10)])
    parecer = models.TextField(validators=[MinLengthValidator(50)])
    recomendacao = models.CharField(max_length=30, choices=Recomendacao.choices)

    history = Historico()

    class Meta:
        ordering = ["criado_em"]
        constraints = [
            models.UniqueConstraint(fields=["banca", "membro"], name="uma_avaliacao_por_membro"),
            models.CheckConstraint(condition=Q(nota__gte=0) & Q(nota__lte=10), name="nota_entre_0_e_10"),
        ]

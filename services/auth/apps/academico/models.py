"""Diretório acadêmico (P1): Curso, Professor e Aluno — donos no auth-service."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from tcc_common.audit.historico import Historico


class Base(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Professor(Base):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="professor")
    nome = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    departamento = models.CharField(max_length=150)
    area_pesquisa = models.CharField(max_length=200, blank=True)

    history = Historico()

    class Meta:
        ordering = ["nome"]
        verbose_name_plural = "professores"

    def __str__(self) -> str:
        return self.nome


class Curso(Base):
    nome = models.CharField(max_length=150)
    codigo = models.CharField(max_length=20, unique=True)
    coordenador = models.ForeignKey(
        Professor, null=True, blank=True, on_delete=models.SET_NULL, related_name="cursos_coordenados"
    )

    history = Historico()

    class Meta:
        ordering = ["nome"]

    def __str__(self) -> str:
        return f"{self.codigo} - {self.nome}"


class Aluno(Base):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="aluno")
    nome = models.CharField(max_length=150)
    matricula = models.CharField(max_length=30, unique=True)
    email = models.EmailField(unique=True)
    curso = models.ForeignKey(Curso, on_delete=models.PROTECT, related_name="alunos")
    orientador_atual = models.ForeignKey(
        Professor, null=True, blank=True, on_delete=models.SET_NULL, related_name="orientandos"
    )

    history = Historico()

    class Meta:
        ordering = ["nome"]

    def __str__(self) -> str:
        return f"{self.nome} ({self.matricula})"

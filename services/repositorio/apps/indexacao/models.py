"""Índice público de monografias (Postgres FTS) e read models de cursos/orientadores."""

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models


class PublicosManager(models.Manager):
    """Queryset base da API pública: SEMPRE filtra ``publico=True``."""

    def get_queryset(self):
        return super().get_queryset().filter(publico=True)


class DocumentoIndexado(models.Model):
    monografia_id = models.UUIDField(primary_key=True)
    titulo = models.CharField(max_length=300)
    titulo_norm = models.CharField(max_length=300, blank=True, default="")
    resumo = models.TextField(blank=True, default="")
    palavras_chave = ArrayField(models.CharField(max_length=60), default=list, blank=True)
    palavras_chave_norm = ArrayField(models.CharField(max_length=60), default=list, blank=True)
    autor_nome = models.CharField(max_length=150, blank=True, default="")
    autor_norm = models.CharField(max_length=150, blank=True, default="")
    orientador_id = models.UUIDField(null=True, blank=True)
    orientador_nome = models.CharField(max_length=150, blank=True, default="")
    orientador_norm = models.CharField(max_length=150, blank=True, default="")
    curso_id = models.UUIDField(null=True, blank=True)
    curso_nome = models.CharField(max_length=150, blank=True, default="")
    ano_defesa = models.PositiveIntegerField(null=True, blank=True)
    texto_completo = models.TextField(blank=True, default="")
    paginas = models.PositiveIntegerField(default=0)
    sem_texto = models.BooleanField(default=False)
    search_vector = SearchVectorField(null=True, blank=True)
    publico = models.BooleanField(default=False)
    publicado_em = models.DateTimeField(null=True, blank=True)
    arquivo_sha256 = models.CharField(max_length=64, blank=True, default="")
    sha256_texto_extraido = models.CharField(max_length=64, blank=True, default="")
    arquivo_local = models.CharField(max_length=300, blank=True, default="")
    extraido_em = models.DateTimeField(null=True, blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    objects = models.Manager()
    publicos = PublicosManager()

    class Meta:
        ordering = ["-publicado_em"]
        indexes = [
            GinIndex(fields=["search_vector"], name="doc_search_vector_gin"),
            models.Index(fields=["publico", "ano_defesa"], name="doc_publico_ano_idx"),
            models.Index(fields=["curso_id"], name="doc_curso_idx"),
            models.Index(fields=["orientador_id"], name="doc_orientador_idx"),
        ]

    def __str__(self) -> str:
        return self.titulo


class CursoRef(models.Model):
    id = models.UUIDField(primary_key=True)
    nome = models.CharField(max_length=150)
    codigo = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["nome"]


class ProfessorRef(models.Model):
    id = models.UUIDField(primary_key=True)
    nome = models.CharField(max_length=150)
    departamento = models.CharField(max_length=150, blank=True)
    area_pesquisa = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["nome"]

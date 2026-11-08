from django.db import models


class FatoMonografia(models.Model):
    """Fato agregado (modelo de leitura) alimentado por eventos monografia.*, banca.* e cadastro.*."""

    monografia_id = models.UUIDField(primary_key=True)
    titulo = models.CharField(max_length=300, blank=True, default="")
    curso_id = models.UUIDField(null=True, blank=True, db_index=True)
    curso_nome = models.CharField(max_length=150, blank=True, default="")
    orientador_id = models.UUIDField(null=True, blank=True, db_index=True)
    orientador_nome = models.CharField(max_length=150, blank=True, default="")
    aluno_id = models.UUIDField(null=True, blank=True, db_index=True)
    status = models.CharField(max_length=20, blank=True, default="", db_index=True)
    submetida_em = models.DateTimeField(null=True, blank=True)
    defendida_em = models.DateTimeField(null=True, blank=True)
    resultado = models.CharField(max_length=20, null=True, blank=True)
    publicada_em = models.DateTimeField(null=True, blank=True)
    ano_defesa = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    atualizado_em = models.DateTimeField(auto_now=True)


class CursoRef(models.Model):
    id = models.UUIDField(primary_key=True)
    nome = models.CharField(max_length=150)


class ProfessorRef(models.Model):
    id = models.UUIDField(primary_key=True)
    nome = models.CharField(max_length=150)

"""Monografia, DocumentoComplementar e read models (AlunoRef, ProfessorRef, CursoRef)."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from apps.monografias.estados import (
    AprovacaoOrientador,
    Status,
    TransicaoInvalida,
    validar_transicao,
)
from tcc_common.api.exceptions import ErroNegocio
from tcc_common.audit.historico import Historico
from tcc_common.events.outbox import registrar_evento
from tcc_common.texto import normalizar


class Base(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# --- Read models (alimentados por cadastro.*) ---------------------------------------


class AlunoRef(models.Model):
    id = models.UUIDField(primary_key=True)
    nome = models.CharField(max_length=150)
    email = models.EmailField()
    matricula = models.CharField(max_length=30, blank=True)
    curso_id = models.UUIDField(null=True)
    orientador_id = models.UUIDField(null=True)


class ProfessorRef(models.Model):
    id = models.UUIDField(primary_key=True)
    nome = models.CharField(max_length=150)
    email = models.EmailField()
    departamento = models.CharField(max_length=150, blank=True)


class CursoRef(models.Model):
    id = models.UUIDField(primary_key=True)
    nome = models.CharField(max_length=150)
    codigo = models.CharField(max_length=20, blank=True)
    coordenador_id = models.UUIDField(null=True)


# --- Monografia ---------------------------------------------------------------------


class Monografia(Base):
    titulo = models.CharField(max_length=300)
    resumo = models.TextField(blank=True, default="")
    palavras_chave = ArrayField(models.CharField(max_length=60), default=list, blank=True)
    aluno_id = models.UUIDField(db_index=True)
    orientador_id = models.UUIDField(db_index=True, null=True, blank=True)
    curso_id = models.UUIDField(db_index=True, null=True, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RASCUNHO, db_index=True)
    aprovacao_orientador = models.CharField(
        max_length=20, choices=AprovacaoOrientador.choices, default=AprovacaoOrientador.PENDENTE
    )
    motivo_rejeicao = models.TextField(blank=True, default="")
    aprovada_orientador_em = models.DateTimeField(null=True, blank=True)
    submetida_em = models.DateTimeField(null=True, blank=True)
    defendida_em = models.DateTimeField(null=True, blank=True)
    resultado_banca = models.CharField(
        max_length=20, null=True, blank=True, choices=[("aprovada", "Aprovada"), ("reprovada", "Reprovada")]
    )
    exige_correcao = models.BooleanField(default=False)
    correcao_validada = models.BooleanField(default=False)

    arquivo = models.FileField(max_length=300, null=True, blank=True)
    arquivo_nome_original = models.CharField(max_length=255, blank=True, default="")
    arquivo_tamanho_bytes = models.BigIntegerField(null=True, blank=True)
    arquivo_sha256 = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    arquivo_sha256_aprovado = models.CharField(max_length=64, null=True, blank=True)
    integridade_ok = models.BooleanField(default=True)
    integridade_verificada_em = models.DateTimeField(null=True, blank=True)
    texto_extraido = models.BooleanField(default=False)
    publicada_em = models.DateTimeField(null=True, blank=True)
    #: título + resumo + palavras-chave normalizados (sem acento) para ?busca=
    busca_normalizada = models.TextField(blank=True, default="", editable=False)

    history = Historico(excluded_fields=["busca_normalizada"])

    class Meta:
        ordering = ["-criado_em"]
        constraints = [
            models.UniqueConstraint(
                fields=["arquivo_sha256"], condition=Q(arquivo_sha256__isnull=False), name="monografia_sha256_unico"
            ),
            models.CheckConstraint(
                condition=~Q(status="publicada") | Q(publicada_em__isnull=False), name="publicada_exige_data"
            ),
        ]

    def __str__(self) -> str:
        return self.titulo

    # --- proteção contra "monografia.status = ..." solto ---
    @classmethod
    def from_db(cls, db, field_names, values):
        inst = super().from_db(db, field_names, values)
        inst._status_original = inst.__dict__.get("status")
        return inst

    def save(self, *args, **kwargs):
        original = getattr(self, "_status_original", None)
        if self._state.adding and self.status != Status.RASCUNHO:
            raise TransicaoInvalida("Monografias nascem como rascunho.")
        if original is not None and original != self.status and not getattr(self, "_transicao_autorizada", False):
            raise TransicaoInvalida("O status só muda pelos métodos de domínio.")
        self.busca_normalizada = normalizar(" ".join([self.titulo, self.resumo, *self.palavras_chave]))
        if kwargs.get("update_fields"):
            kwargs["update_fields"] = {*kwargs["update_fields"], "busca_normalizada"}
        super().save(*args, **kwargs)
        self._status_original = self.status
        self._transicao_autorizada = False

    def _transitar(self, destino: str) -> None:
        validar_transicao(self.status, destino)
        self.status = destino
        self._transicao_autorizada = True

    # --- payloads de eventos ---
    def payload_base(self) -> dict:
        return {
            "id": self.id,
            "titulo": self.titulo,
            "status": self.status,
            "aprovacao_orientador": self.aprovacao_orientador,
            "aluno_id": self.aluno_id,
            "orientador_id": self.orientador_id,
            "curso_id": self.curso_id,
        }

    @property
    def ano_defesa(self) -> int | None:
        data = self.defendida_em or self.publicada_em
        return timezone.localtime(data).year if data else None

    # --- métodos de domínio ---
    def validar_para_submissao(self) -> None:
        faltando = []
        if not self.arquivo or not self.arquivo_sha256:
            faltando.append("arquivo")
        if not self.titulo.strip():
            faltando.append("titulo")
        if not self.resumo.strip():
            faltando.append("resumo")
        if len([p for p in self.palavras_chave if p.strip()]) < settings.MIN_PALAVRAS_CHAVE:
            faltando.append(f"palavras_chave (mínimo {settings.MIN_PALAVRAS_CHAVE})")
        if not self.orientador_id:
            faltando.append("orientador")
        if faltando:
            raise ErroNegocio(
                "Monografia incompleta para submissão.",
                codigo="submissao_incompleta",
                status_code=400,
                detalhes={"faltando": faltando},
            )

    @transaction.atomic
    def submeter(self) -> None:
        """rascunho -> em_avaliacao (exige PDF + metadados). Publica ``monografia.submetida``."""
        self.validar_para_submissao()
        self._transitar(Status.EM_AVALIACAO)
        self.submetida_em = timezone.now()
        self.aprovacao_orientador = AprovacaoOrientador.PENDENTE
        self.motivo_rejeicao = ""
        self.texto_extraido = False
        self.save()
        registrar_evento(
            "monografia.submetida",
            {
                **self.payload_base(),
                "sha256": self.arquivo_sha256,
                "submetida_em": self.submetida_em,
            },
        )

    @transaction.atomic
    def aprovar_orientador(self) -> None:
        """Aprovação do orientador: grava o snapshot de integridade (``arquivo_sha256_aprovado``)."""
        if self.status != Status.EM_AVALIACAO or self.aprovacao_orientador != AprovacaoOrientador.PENDENTE:
            raise TransicaoInvalida(
                "Só é possível aprovar uma submissão em avaliação e pendente.",
                detalhes={"status": self.status, "aprovacao": self.aprovacao_orientador},
            )
        self.aprovacao_orientador = AprovacaoOrientador.APROVADA
        self.aprovada_orientador_em = timezone.now()
        self.arquivo_sha256_aprovado = self.arquivo_sha256
        self.integridade_ok = True
        self.save()
        registrar_evento(
            "monografia.aprovada_orientador",
            {
                **self.payload_base(),
                "sha256_aprovado": self.arquivo_sha256_aprovado,
            },
        )

    @transaction.atomic
    def rejeitar_orientador(self, motivo: str) -> None:
        if self.aprovacao_orientador != AprovacaoOrientador.PENDENTE:
            raise TransicaoInvalida("A submissão não está pendente de aprovação.")
        self._transitar(Status.RASCUNHO)
        self.aprovacao_orientador = AprovacaoOrientador.REJEITADA
        self.motivo_rejeicao = motivo
        self.save()
        registrar_evento("monografia.rejeitada_orientador", {**self.payload_base(), "motivo": motivo})

    @transaction.atomic
    def registrar_resultado_banca(self, resultado: str, exige_correcao: bool, defendida_em=None) -> None:
        if self.aprovacao_orientador != AprovacaoOrientador.APROVADA:
            raise TransicaoInvalida("Resultado de banca sem aprovação do orientador.")
        destino = Status.APROVADA if resultado == "aprovada" else Status.REPROVADA
        self._transitar(destino)
        self.resultado_banca = resultado
        self.exige_correcao = bool(exige_correcao) and resultado == "aprovada"
        self.correcao_validada = False
        self.defendida_em = defendida_em or timezone.now()
        self.save()
        registrar_evento(
            "monografia.resultado_registrado",
            {
                **self.payload_base(),
                "resultado": resultado,
                "exige_correcao": self.exige_correcao,
                "defendida_em": self.defendida_em,
            },
        )
        self.tentar_publicar()

    def pendencias_publicacao(self) -> list[str]:
        """Pré-condições de P7 que ainda faltam (lista vazia = pode publicar)."""
        pend = []
        if self.status != Status.APROVADA:
            pend.append("status_aprovada")
        if self.exige_correcao:
            if not self.documentos.filter(tipo=DocumentoComplementar.Tipo.VERSAO_CORRIGIDA).exists():
                pend.append("versao_corrigida")
            if not self.correcao_validada:
                pend.append("correcao_validada_orientador")
        if not self.documentos.filter(tipo=DocumentoComplementar.Tipo.TERMO, assinado_validado=True).exists():
            pend.append("termo_autorizacao_assinado")
        if not self.integridade_ok:
            pend.append("integridade_ok")
        return pend

    @transaction.atomic
    def tentar_publicar(self) -> bool:
        """Publica se e somente se todas as pré-condições (P7) forem atendidas."""
        if self.pendencias_publicacao():
            return False
        self.publicar()
        return True

    def publicar(self) -> None:
        self._transitar(Status.PUBLICADA)
        self.publicada_em = timezone.now()
        self.save()
        aluno = AlunoRef.objects.filter(pk=self.aluno_id).first()
        orientador = ProfessorRef.objects.filter(pk=self.orientador_id).first() if self.orientador_id else None
        curso = CursoRef.objects.filter(pk=self.curso_id).first() if self.curso_id else None
        registrar_evento(
            "monografia.publicada",
            {
                **self.payload_base(),
                "resumo": self.resumo,
                "palavras_chave": self.palavras_chave,
                "autor_nome": aluno.nome if aluno else "",
                "autor_email": aluno.email if aluno else "",
                "orientador_nome": orientador.nome if orientador else "",
                "curso_nome": curso.nome if curso else "",
                "ano_defesa": self.ano_defesa,
                "defendida_em": self.defendida_em,
                "sha256": self.arquivo_sha256,
                "publicada_em": self.publicada_em,
            },
        )


def caminho_documento(instance, filename: str) -> str:
    return f"monografias/{instance.monografia_id}/documentos/{filename}"


class DocumentoComplementar(Base):
    class Tipo(models.TextChoices):
        ATA = "ata_defesa", "Ata de defesa"
        TERMO = "termo_autorizacao_publicacao", "Termo de autorização de publicação"
        COMPROVANTE = "comprovante_correcao_ortografica", "Comprovante de correção ortográfica"
        VERSAO_CORRIGIDA = "versao_corrigida", "Versão corrigida"

    monografia = models.ForeignKey(Monografia, on_delete=models.CASCADE, related_name="documentos")
    tipo = models.CharField(max_length=40, choices=Tipo.choices)
    arquivo = models.FileField(max_length=300, upload_to=caminho_documento)
    arquivo_nome_original = models.CharField(max_length=255, blank=True, default="")
    tamanho_bytes = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, db_index=True)
    assinado_validado = models.BooleanField(default=False)
    validado_por_id = models.UUIDField(null=True, blank=True)
    validado_em = models.DateTimeField(null=True, blank=True)
    enviado_por_id = models.UUIDField(null=True, blank=True)

    history = Historico()

    class Meta:
        ordering = ["-criado_em"]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} — {self.monografia_id}"

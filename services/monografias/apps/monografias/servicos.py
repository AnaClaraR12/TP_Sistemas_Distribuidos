"""Casos de uso do monografias-service (upload, submissão, integridade, documentos)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.monografias import arquivos
from apps.monografias.estados import AprovacaoOrientador, Status, TransicaoInvalida
from apps.monografias.models import DocumentoComplementar, Monografia
from tcc_common.api.exceptions import ErroNegocio
from tcc_common.audit.auditoria import registrar_auditoria
from tcc_common.cache.redis import adquirir_lock, liberar_lock, verificar_rate_limit
from tcc_common.events.outbox import registrar_evento

logger = logging.getLogger(__name__)


def chave_lock_upload(monografia_id) -> str:
    return f"upload_em_andamento:{monografia_id}"


@dataclass
class ResultadoUpload:
    monografia: Monografia
    idempotente: bool


def _erro_lock() -> ErroNegocio:
    return ErroNegocio(
        "Já existe um upload/processamento em andamento para esta monografia. Aguarde a conclusão.",
        codigo="upload_em_andamento",
        status_code=409,
    )


def processar_upload(monografia: Monografia, arquivo: UploadedFile, usuario, request=None) -> ResultadoUpload:
    """Upload do PDF principal — validações na ordem da Fase 2, item 4.

    (1) autenticação/dono/rascunho são verificados pela view antes desta função.
    """
    if monografia.status != Status.RASCUNHO:
        raise TransicaoInvalida("Upload permitido apenas em rascunho.", codigo="upload_nao_permitido")
    if monografia.aprovacao_orientador == AprovacaoOrientador.APROVADA:
        raise ErroNegocio("Arquivo imutável após aprovação do orientador.", codigo="arquivo_imutavel")

    # (2) rate limit por usuário
    permitido, retry = verificar_rate_limit(f"rl:submissao:{usuario.id}", settings.SUBMISSOES_POR_HORA, 3600)
    if not permitido:
        raise ErroNegocio(
            "Limite de envios por hora atingido.",
            codigo="limite_submissoes",
            status_code=429,
            headers={"Retry-After": str(retry)},
            detalhes={"retry_after": retry},
        )

    # (3) lock de upload em andamento
    chave = chave_lock_upload(monografia.id)
    valor = getattr(request, "request_id", None) or "upload"
    if not adquirir_lock(chave, valor, settings.UPLOAD_LOCK_TTL_S):
        raise _erro_lock()
    try:
        # (4) formato, (5) tamanho, (6) SHA-256
        pdf = arquivos.validar_pdf(arquivo)
        # (7) deduplicação
        if pdf.sha256 == monografia.arquivo_sha256:
            return ResultadoUpload(monografia, idempotente=True)
        if Monografia.objects.filter(arquivo_sha256=pdf.sha256).exclude(pk=monografia.pk).exists():
            raise ErroNegocio("Este arquivo já foi submetido.", codigo="arquivo_duplicado", status_code=409)
        # (8) grava em media/monografias/<uuid>/<sha256>.pdf
        antigo = monografia.arquivo.name if monografia.arquivo else None
        nome = arquivos.salvar(arquivo, f"monografias/{monografia.id}/{pdf.sha256}.pdf")
        monografia.arquivo.name = nome
        monografia.arquivo_sha256 = pdf.sha256
        monografia.arquivo_tamanho_bytes = pdf.tamanho
        monografia.arquivo_nome_original = pdf.nome_original
        monografia.aprovacao_orientador = AprovacaoOrientador.PENDENTE
        monografia.texto_extraido = False
        try:
            with transaction.atomic():
                monografia.save()
                registrar_auditoria(
                    "upload_arquivo",
                    "monografia",
                    monografia.id,
                    request=request,
                    usuario=usuario,
                    detalhes={"sha256": pdf.sha256, "tamanho": pdf.tamanho},
                )
        except IntegrityError as exc:  # corrida na deduplicação
            default_storage.delete(nome)
            raise ErroNegocio("Este arquivo já foi submetido.", codigo="arquivo_duplicado", status_code=409) from exc
        if antigo and antigo != nome:
            default_storage.delete(antigo)
        # (9) o status continua rascunho
        return ResultadoUpload(monografia, idempotente=False)
    finally:
        # upload feito antes de submeter: lock liberado ao fim da requisição
        liberar_lock(chave, valor)


def submeter(monografia: Monografia, usuario, request=None) -> Monografia:
    """rascunho -> em_avaliacao; o lock fica até a extração de texto terminar (consumer)."""
    chave = chave_lock_upload(monografia.id)
    valor = getattr(request, "request_id", None) or "submissao"
    if not adquirir_lock(chave, valor, settings.UPLOAD_LOCK_TTL_S):
        raise _erro_lock()
    try:
        with transaction.atomic():
            monografia.submeter()
            registrar_auditoria("submissao", "monografia", monografia.id, request=request, usuario=usuario)
    except Exception:
        liberar_lock(chave, valor)
        raise
    return monografia


def verificar_integridade(monografia: Monografia, usuario=None, request=None) -> dict:
    """Recalcula o SHA-256 em disco e compara com o snapshot aprovado (ou o atual)."""
    if not monografia.arquivo:
        raise ErroNegocio("Monografia sem arquivo.", codigo="sem_arquivo", status_code=400)
    esperado = monografia.arquivo_sha256_aprovado or monografia.arquivo_sha256
    try:
        atual = arquivos.sha256_do_storage(monografia.arquivo.name)
    except FileNotFoundError:
        atual = "arquivo_ausente"
    ok = atual == esperado
    with transaction.atomic():
        Monografia.objects.filter(pk=monografia.pk).update(integridade_ok=ok, integridade_verificada_em=timezone.now())
        monografia.refresh_from_db()
        if not ok:
            registrar_evento(
                "monografia.integridade_violada",
                {
                    **monografia.payload_base(),
                    "sha_esperado": esperado,
                    "sha_atual": atual,
                },
            )
            registrar_auditoria(
                "integridade_violada",
                "monografia",
                monografia.id,
                request=request,
                usuario=usuario,
                detalhes={"sha_esperado": esperado, "sha_atual": atual},
                nivel="critico",
            )
        elif monografia.status == Status.APROVADA:
            monografia.tentar_publicar()
    return {
        "integridade_ok": ok,
        "sha_esperado": esperado,
        "sha_atual": atual,
        "verificada_em": monografia.integridade_verificada_em,
    }


# --- documentos complementares --------------------------------------------------------

#: quem pode enviar cada tipo (além do admin)
QUEM_ENVIA = {
    DocumentoComplementar.Tipo.TERMO: {"aluno"},
    DocumentoComplementar.Tipo.VERSAO_CORRIGIDA: {"aluno"},
    DocumentoComplementar.Tipo.COMPROVANTE: {"aluno"},
    DocumentoComplementar.Tipo.ATA: {"coordenador", "orientador"},
}


def enviar_documento(
    monografia: Monografia, tipo: str, arquivo: UploadedFile, usuario, request=None
) -> DocumentoComplementar:
    if monografia.status == Status.PUBLICADA:
        raise ErroNegocio("Monografia publicada é imutável.", codigo="monografia_publicada_imutavel")
    if tipo == DocumentoComplementar.Tipo.VERSAO_CORRIGIDA and not (
        monografia.status == Status.APROVADA and monografia.exige_correcao
    ):
        raise ErroNegocio("Versão corrigida só é aceita após aprovação com ressalvas.", codigo="correcao_nao_exigida")
    if tipo in (DocumentoComplementar.Tipo.TERMO, DocumentoComplementar.Tipo.ATA) and monografia.status not in (
        Status.EM_AVALIACAO,
        Status.APROVADA,
    ):
        raise ErroNegocio("Documento não aceito no status atual.", codigo="documento_nao_permitido")
    pdf = arquivos.validar_pdf(arquivo)
    if (
        tipo == DocumentoComplementar.Tipo.VERSAO_CORRIGIDA
        and Monografia.objects.filter(arquivo_sha256=pdf.sha256).exclude(pk=monografia.pk).exists()
    ):
        raise ErroNegocio("Este arquivo já foi submetido.", codigo="arquivo_duplicado", status_code=409)
    with transaction.atomic():
        doc = DocumentoComplementar(
            monografia=monografia,
            tipo=tipo,
            sha256=pdf.sha256,
            tamanho_bytes=pdf.tamanho,
            arquivo_nome_original=pdf.nome_original,
            enviado_por_id=usuario.id,
        )
        arquivo.seek(0)
        doc.arquivo.save(f"{tipo}-{pdf.sha256[:16]}.pdf", arquivo, save=False)
        doc.save()
        if tipo == DocumentoComplementar.Tipo.VERSAO_CORRIGIDA:
            Monografia.objects.filter(pk=monografia.pk).update(correcao_validada=False)
            monografia.refresh_from_db()
        registrar_evento("documento.enviado", {"monografia_id": monografia.id, "tipo": tipo, "documento_id": doc.id})
        registrar_auditoria(
            "envio_documento",
            "monografia",
            monografia.id,
            request=request,
            usuario=usuario,
            detalhes={"tipo": tipo, "sha256": pdf.sha256},
        )
        monografia.tentar_publicar()
    return doc


def validar_assinatura(doc: DocumentoComplementar, usuario, request=None) -> DocumentoComplementar:
    if doc.tipo != DocumentoComplementar.Tipo.TERMO:
        raise ErroNegocio(
            "Apenas o termo de autorização tem assinatura validada.", codigo="tipo_invalido", status_code=400
        )
    with transaction.atomic():
        doc.assinado_validado = True
        doc.validado_por_id = usuario.id
        doc.validado_em = timezone.now()
        doc.save()
        registrar_auditoria("validacao_termo", "monografia", doc.monografia_id, request=request, usuario=usuario)
        doc.monografia.tentar_publicar()
    return doc


def validar_correcao(monografia: Monografia, usuario, request=None) -> Monografia:
    """Orientador confirma a versão corrigida: ela vira o arquivo oficial (novo snapshot de integridade)."""
    if monografia.status != Status.APROVADA or not monografia.exige_correcao:
        raise ErroNegocio("Não há correção a validar.", codigo="correcao_nao_exigida")
    doc = monografia.documentos.filter(tipo=DocumentoComplementar.Tipo.VERSAO_CORRIGIDA).order_by("-criado_em").first()
    if doc is None:
        raise ErroNegocio("A versão corrigida ainda não foi enviada.", codigo="versao_corrigida_ausente")
    with transaction.atomic():
        monografia.arquivo.name = doc.arquivo.name
        monografia.arquivo_sha256 = doc.sha256
        monografia.arquivo_sha256_aprovado = doc.sha256
        monografia.arquivo_tamanho_bytes = doc.tamanho_bytes
        monografia.correcao_validada = True
        monografia.integridade_ok = True
        monografia.save()
        registrar_auditoria(
            "validacao_correcao",
            "monografia",
            monografia.id,
            request=request,
            usuario=usuario,
            detalhes={"sha256": doc.sha256},
        )
        monografia.tentar_publicar()
    return monografia

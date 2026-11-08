"""Consumers do repositorio-service: extração assíncrona, publicação e read models."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.indexacao import extracao
from apps.indexacao.cache import invalidar_cache_busca
from apps.indexacao.models import CursoRef, DocumentoIndexado, ProfessorRef
from tcc_common.events.outbox import registrar_evento
from tcc_common.texto import normalizar

logger = logging.getLogger(__name__)


def _aplicar_metadados(doc: DocumentoIndexado, d: dict) -> None:
    doc.titulo = d.get("titulo") or doc.titulo
    doc.titulo_norm = normalizar(doc.titulo)
    if "resumo" in d:
        doc.resumo = d.get("resumo") or ""
    if "palavras_chave" in d:
        doc.palavras_chave = list(d.get("palavras_chave") or [])
        doc.palavras_chave_norm = [normalizar(p) for p in doc.palavras_chave]
    if d.get("autor_nome"):
        doc.autor_nome = d["autor_nome"]
        doc.autor_norm = normalizar(d["autor_nome"])
    doc.orientador_id = d.get("orientador_id") or doc.orientador_id
    if d.get("orientador_nome"):
        doc.orientador_nome = d["orientador_nome"]
        doc.orientador_norm = normalizar(d["orientador_nome"])
    doc.curso_id = d.get("curso_id") or doc.curso_id
    if d.get("curso_nome"):
        doc.curso_nome = d["curso_nome"]


def _extrair_para(doc: DocumentoIndexado, caminho: str, sha: str) -> extracao.TextoExtraido:
    resultado = extracao.extrair_texto(caminho)
    doc.texto_completo = resultado.texto
    doc.paginas = resultado.paginas
    doc.sem_texto = resultado.sem_texto
    doc.sha256_texto_extraido = sha
    doc.extraido_em = timezone.now()
    return resultado


def on_submetida(envelope: dict) -> None:
    """monografia.submetida -> baixa o PDF, extrai o texto e indexa (publico=False)."""
    d = envelope["data"]
    caminho, sha = extracao.baixar_pdf(d["id"])  # DownloadFalhou => retry
    try:
        doc, _ = DocumentoIndexado.objects.get_or_create(monografia_id=d["id"], defaults={"titulo": d["titulo"]})
        _aplicar_metadados(doc, d)
        doc.arquivo_sha256 = sha
        try:
            resultado = _extrair_para(doc, caminho, sha)
        except extracao.PdfCorrompido as exc:
            doc.save()
            registrar_evento(
                "monografia.extracao_falhou",
                {
                    "id": d["id"],
                    "motivo": str(exc)[:500],
                    "orientador_id": d.get("orientador_id"),
                    "aluno_id": d.get("aluno_id"),
                    "titulo": d.get("titulo"),
                },
            )
            return
        doc.save()
        extracao.atualizar_vetor(doc)
        registrar_evento(
            "monografia.texto_extraido",
            {
                "id": d["id"],
                "paginas": resultado.paginas,
                "sem_texto": resultado.sem_texto,
                "orientador_id": d.get("orientador_id"),
                "aluno_id": d.get("aluno_id"),
                "titulo": d.get("titulo"),
            },
        )
    finally:
        os.unlink(caminho)


def _falha_definitiva_submetida(envelope: dict, exc: Exception) -> None:
    d = envelope["data"]
    registrar_evento(
        "monografia.extracao_falhou",
        {
            "id": d["id"],
            "motivo": f"Falha após retries: {exc!r}"[:500],
            "orientador_id": d.get("orientador_id"),
            "aluno_id": d.get("aluno_id"),
            "titulo": d.get("titulo"),
        },
    )


on_submetida.falha_definitiva = _falha_definitiva_submetida


def _pasta_publicados() -> Path:
    p = Path(settings.MEDIA_ROOT) / "publicados"
    p.mkdir(parents=True, exist_ok=True)
    return p


def on_publicada(envelope: dict) -> None:
    """monografia.publicada -> torna público, guarda cópia do PDF, reindexa e invalida o cache."""
    d = envelope["data"]
    doc, _ = DocumentoIndexado.objects.get_or_create(monografia_id=d["id"], defaults={"titulo": d["titulo"]})
    _aplicar_metadados(doc, d)
    caminho, sha = extracao.baixar_pdf(d["id"])
    try:
        if d.get("sha256") and sha != d["sha256"]:
            raise extracao.DownloadFalhou("hash do PDF baixado difere do publicado")
        if doc.sha256_texto_extraido != sha:  # versão corrigida ou extração anterior falhou
            try:
                _extrair_para(doc, caminho, sha)
            except extracao.PdfCorrompido:
                logger.warning("pdf_publicado_sem_texto", extra={"monografia_id": d["id"]})
        destino = _pasta_publicados() / f"{d['id']}.pdf"
        shutil.copyfile(caminho, destino)
    finally:
        os.unlink(caminho)
    doc.arquivo_sha256 = sha
    doc.arquivo_local = str(destino)
    doc.publico = True
    doc.publicado_em = parse_datetime(d["publicada_em"]) if d.get("publicada_em") else timezone.now()
    doc.ano_defesa = d.get("ano_defesa") or doc.publicado_em.year
    doc.save()
    extracao.atualizar_vetor(doc)
    # só depois do commit: uma busca concorrente não pode gravar dado velho na versão nova do cache
    transaction.on_commit(invalidar_cache_busca)
    registrar_evento("repositorio.indexado", {"monografia_id": d["id"]})


def on_excluida(envelope: dict) -> None:
    DocumentoIndexado.objects.filter(monografia_id=envelope["data"]["id"], publico=False).delete()


def on_cadastro(envelope: dict) -> None:
    _, entidade, acao = envelope["type"].split(".")
    d = envelope["data"]
    modelo = {"curso": CursoRef, "professor": ProfessorRef}.get(entidade)
    if modelo is None:
        return
    if acao == "deleted":
        modelo.objects.filter(pk=d["id"]).delete()
    elif entidade == "curso":
        CursoRef.objects.update_or_create(pk=d["id"], defaults={"nome": d["nome"], "codigo": d.get("codigo") or ""})
    else:
        ProfessorRef.objects.update_or_create(
            pk=d["id"],
            defaults={
                "nome": d["nome"],
                "departamento": d.get("departamento") or "",
                "area_pesquisa": d.get("area_pesquisa") or "",
            },
        )
    # só depois do commit: uma busca concorrente não pode gravar dado velho na versão nova do cache
    transaction.on_commit(invalidar_cache_busca)


HANDLERS = {
    "monografia.submetida": on_submetida,
    "monografia.publicada": on_publicada,
    "monografia.excluida": on_excluida,
    "cadastro.#": on_cadastro,
}

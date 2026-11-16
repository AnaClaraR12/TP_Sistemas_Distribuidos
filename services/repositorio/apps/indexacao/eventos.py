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


def _aplicar_metadados(doc: DocumentoIndexado, mono: dict) -> None:
    doc.titulo = mono.get("titulo") or doc.titulo
    doc.titulo_norm = normalizar(doc.titulo)
    if "resumo" in mono:
        doc.resumo = mono.get("resumo") or ""
    if "palavras_chave" in mono:
        doc.palavras_chave = list(mono.get("palavras_chave") or [])
        doc.palavras_chave_norm = [normalizar(p) for p in doc.palavras_chave]
    if mono.get("autor_nome"):
        doc.autor_nome = mono["autor_nome"]
        doc.autor_norm = normalizar(mono["autor_nome"])
    doc.orientador_id = mono.get("orientador_id") or doc.orientador_id
    if mono.get("orientador_nome"):
        doc.orientador_nome = mono["orientador_nome"]
        doc.orientador_norm = normalizar(mono["orientador_nome"])
    doc.curso_id = mono.get("curso_id") or doc.curso_id
    if mono.get("curso_nome"):
        doc.curso_nome = mono["curso_nome"]


def _extrair_para(doc: DocumentoIndexado, caminho: str, sha: str) -> extracao.TextoExtraido:
    resultado = extracao.extrair_texto(caminho)
    doc.texto_completo = resultado.texto
    doc.paginas = resultado.paginas
    doc.sem_texto = resultado.sem_texto
    doc.sha256_texto_extraido = sha
    doc.extraido_em = timezone.now()
    return resultado


def _avisar_falha_extracao(mono: dict, motivo: str) -> None:
    registrar_evento(
        "monografia.extracao_falhou",
        {
            "id": mono["id"],
            "motivo": motivo[:500],
            "orientador_id": mono.get("orientador_id"),
            "aluno_id": mono.get("aluno_id"),
            "titulo": mono.get("titulo"),
        },
    )


def on_submetida(envelope: dict) -> None:
    """monografia.submetida -> baixa o PDF, extrai o texto e indexa (publico=False)."""
    mono = envelope["data"]
    caminho, sha = extracao.baixar_pdf(mono["id"])  # DownloadFalhou => retry
    try:
        doc, _ = DocumentoIndexado.objects.get_or_create(monografia_id=mono["id"], defaults={"titulo": mono["titulo"]})
        _aplicar_metadados(doc, mono)
        doc.arquivo_sha256 = sha
        try:
            resultado = _extrair_para(doc, caminho, sha)
        except extracao.PdfCorrompido as exc:
            doc.save()
            _avisar_falha_extracao(mono, str(exc))
            return
        doc.save()
        extracao.atualizar_vetor(doc)
        registrar_evento(
            "monografia.texto_extraido",
            {
                "id": mono["id"],
                "paginas": resultado.paginas,
                "sem_texto": resultado.sem_texto,
                "orientador_id": mono.get("orientador_id"),
                "aluno_id": mono.get("aluno_id"),
                "titulo": mono.get("titulo"),
            },
        )
    finally:
        os.unlink(caminho)


def _falha_definitiva_submetida(envelope: dict, exc: Exception) -> None:
    _avisar_falha_extracao(envelope["data"], f"Falha após retries: {exc!r}")


on_submetida.falha_definitiva = _falha_definitiva_submetida


def _pasta_publicados() -> Path:
    p = Path(settings.MEDIA_ROOT) / "publicados"
    p.mkdir(parents=True, exist_ok=True)
    return p


def on_publicada(envelope: dict) -> None:
    """monografia.publicada -> torna público, guarda cópia do PDF, reindexa e invalida o cache."""
    mono = envelope["data"]
    doc, _ = DocumentoIndexado.objects.get_or_create(monografia_id=mono["id"], defaults={"titulo": mono["titulo"]})
    _aplicar_metadados(doc, mono)
    caminho, sha = extracao.baixar_pdf(mono["id"])
    try:
        if mono.get("sha256") and sha != mono["sha256"]:
            raise extracao.DownloadFalhou("hash do PDF baixado difere do publicado")
        if doc.sha256_texto_extraido != sha:  # versão corrigida ou extração anterior falhou
            try:
                _extrair_para(doc, caminho, sha)
            except extracao.PdfCorrompido:
                logger.warning("pdf_publicado_sem_texto", extra={"monografia_id": mono["id"]})
        destino = _pasta_publicados() / f"{mono['id']}.pdf"
        shutil.copyfile(caminho, destino)
    finally:
        os.unlink(caminho)
    doc.arquivo_sha256 = sha
    doc.arquivo_local = str(destino)
    doc.publico = True
    doc.publicado_em = parse_datetime(mono["publicada_em"]) if mono.get("publicada_em") else timezone.now()
    doc.ano_defesa = mono.get("ano_defesa") or doc.publicado_em.year
    doc.save()
    extracao.atualizar_vetor(doc)
    # só depois do commit: uma busca concorrente não pode gravar dado velho na versão nova do cache
    transaction.on_commit(invalidar_cache_busca)
    registrar_evento("repositorio.indexado", {"monografia_id": mono["id"]})


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

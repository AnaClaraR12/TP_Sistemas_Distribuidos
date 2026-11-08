"""Download do PDF (HTTP interno) e extração de texto com pdfplumber (fallback pypdf)."""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import time
from dataclasses import dataclass

import requests
from django.conf import settings
from django.contrib.postgres.search import SearchVector
from django.db.models import Value

from apps.indexacao.models import DocumentoIndexado
from tcc_common.texto import normalizar

logger = logging.getLogger(__name__)


class PdfCorrompido(Exception):
    """Erro permanente: não adianta tentar de novo."""


class DownloadFalhou(Exception):
    """Erro transitório (serviço fora, timeout) -> retry pelo consumer."""


@dataclass
class TextoExtraido:
    texto: str
    paginas: int
    sem_texto: bool


def baixar_pdf(monografia_id) -> tuple[str, str]:
    """Baixa em streaming para arquivo temporário. Retorna (caminho, sha256)."""
    url = f"{settings.SERVICOS_URLS['monografias']}/internal/monografias/{monografia_id}/arquivo/"
    try:
        resp = requests.get(url, headers={"X-Service-Token": settings.SERVICE_TOKEN}, stream=True, timeout=30)
    except requests.RequestException as exc:
        raise DownloadFalhou(repr(exc)) from exc
    if resp.status_code != 200:
        raise DownloadFalhou(f"HTTP {resp.status_code}")
    sha = hashlib.sha256()
    fd, caminho = tempfile.mkstemp(suffix=".pdf")
    with os.fdopen(fd, "wb") as f:
        for bloco in resp.iter_content(1024 * 1024):
            sha.update(bloco)
            f.write(bloco)
    return caminho, sha.hexdigest()


def _com_pdfplumber(caminho: str) -> TextoExtraido:
    import pdfplumber

    partes, inicio = [], time.monotonic()
    with pdfplumber.open(caminho) as pdf:
        total = len(pdf.pages)
        for i, pagina in enumerate(pdf.pages):
            if i >= settings.EXTRACAO_MAX_PAGINAS or time.monotonic() - inicio > settings.EXTRACAO_TIMEOUT_S:
                logger.warning("extracao_truncada", extra={"paginas_lidas": i, "total": total})
                break
            partes.append(pagina.extract_text() or "")
            pagina.flush_cache()
    texto = "\n".join(partes).strip()
    return TextoExtraido(texto, total, not texto)


def _com_pypdf(caminho: str) -> TextoExtraido:
    from pypdf import PdfReader

    leitor = PdfReader(caminho)
    partes = [(p.extract_text() or "") for p in leitor.pages[: settings.EXTRACAO_MAX_PAGINAS]]
    texto = "\n".join(partes).strip()
    return TextoExtraido(texto, len(leitor.pages), not texto)


def extrair_texto(caminho: str) -> TextoExtraido:
    """PDF escaneado sem texto -> ``sem_texto=True`` (não é erro). Corrompido -> ``PdfCorrompido``."""
    try:
        return _com_pdfplumber(caminho)
    except Exception as exc:  # noqa: BLE001
        logger.info("pdfplumber_falhou_tentando_pypdf", extra={"erro": repr(exc)})
        try:
            return _com_pypdf(caminho)
        except Exception as exc2:  # noqa: BLE001
            raise PdfCorrompido(f"PDF ilegível: {exc2!r}") from exc2


def atualizar_vetor(doc: DocumentoIndexado) -> None:
    """Pesos: título A, palavras-chave B, resumo B, corpo C — sobre texto sem acentos."""
    cfg = settings.FTS_CONFIG
    vetor = (
        SearchVector(Value(normalizar(doc.titulo)), weight="A", config=cfg)
        + SearchVector(Value(normalizar(" ".join(doc.palavras_chave))), weight="B", config=cfg)
        + SearchVector(Value(normalizar(doc.resumo)), weight="B", config=cfg)
        + SearchVector(Value(normalizar(doc.texto_completo[: settings.FTS_MAX_CHARS])), weight="C", config=cfg)
    )
    DocumentoIndexado.objects.filter(pk=doc.pk).update(search_vector=vetor)

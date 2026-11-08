"""Validação e gravação de PDFs: formato (extensão + magic bytes + Content-Type),
tamanho em streaming, SHA-256 em chunks e nome de arquivo controlado pelo servidor."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile

from tcc_common.api.exceptions import ErroNegocio

MAGIC_PDF = b"%PDF-"
CONTENT_TYPES_PDF = {"application/pdf", "application/x-pdf"}
CHUNK = 1024 * 1024


@dataclass(frozen=True)
class PdfValidado:
    sha256: str
    tamanho: int
    nome_original: str


def limite_bytes() -> int:
    return settings.MAX_UPLOAD_MB * 1024 * 1024


def validar_formato(arquivo: UploadedFile) -> None:
    """Extensão ``.pdf`` E magic bytes ``%PDF-`` E Content-Type — divergência = 415."""
    nome = (arquivo.name or "").lower()
    arquivo.seek(0)
    cabecalho = arquivo.read(len(MAGIC_PDF))
    arquivo.seek(0)
    problemas = []
    if not nome.endswith(".pdf"):
        problemas.append("extensao")
    if cabecalho != MAGIC_PDF:
        problemas.append("conteudo_nao_e_pdf")
    if (arquivo.content_type or "").split(";")[0].strip().lower() not in CONTENT_TYPES_PDF:
        problemas.append("content_type")
    if problemas:
        raise ErroNegocio(
            "Somente arquivos PDF são aceitos.",
            codigo="formato_invalido",
            status_code=415,
            detalhes={"problemas": problemas},
        )


def validar_tamanho_e_hash(arquivo: UploadedFile) -> tuple[str, int]:
    """Lê em chunks (sem carregar tudo na memória): calcula SHA-256 e aborta se exceder o limite."""
    limite = limite_bytes()
    if arquivo.size is not None and arquivo.size > limite:
        raise ErroNegocio(
            f"Arquivo excede {settings.MAX_UPLOAD_MB} MB.",
            codigo="arquivo_muito_grande",
            status_code=413,
            detalhes={"limite_mb": settings.MAX_UPLOAD_MB},
        )
    sha = hashlib.sha256()
    total = 0
    arquivo.seek(0)
    for bloco in arquivo.chunks(CHUNK):
        total += len(bloco)
        if total > limite:
            raise ErroNegocio(
                f"Arquivo excede {settings.MAX_UPLOAD_MB} MB.",
                codigo="arquivo_muito_grande",
                status_code=413,
                detalhes={"limite_mb": settings.MAX_UPLOAD_MB},
            )
        sha.update(bloco)
    arquivo.seek(0)
    if total == 0:
        raise ErroNegocio("Arquivo vazio.", codigo="arquivo_vazio", status_code=400)
    return sha.hexdigest(), total


def validar_pdf(arquivo: UploadedFile) -> PdfValidado:
    validar_formato(arquivo)
    sha, tamanho = validar_tamanho_e_hash(arquivo)
    return PdfValidado(sha256=sha, tamanho=tamanho, nome_original=(arquivo.name or "")[:255])


def salvar(arquivo: UploadedFile, caminho: str) -> str:
    """Grava no storage num caminho definido pelo servidor (evita path traversal)."""
    if default_storage.exists(caminho):
        default_storage.delete(caminho)
    arquivo.seek(0)
    return default_storage.save(caminho, arquivo)


def sha256_do_storage(nome: str) -> str:
    sha = hashlib.sha256()
    with default_storage.open(nome, "rb") as f:
        for bloco in iter(lambda: f.read(CHUNK), b""):
            sha.update(bloco)
    return sha.hexdigest()

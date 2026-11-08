"""Normalização de texto para busca insensível a acentos e caixa ("monografia" = "monografía")."""

from __future__ import annotations

import re
import unicodedata

_ESPACOS = re.compile(r"\s+")


def remover_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    """minúsculas, sem acentos, espaços colapsados."""
    return _ESPACOS.sub(" ", remover_acentos(texto).lower()).strip()

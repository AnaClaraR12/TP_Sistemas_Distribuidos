"""Cache-aside da busca pública no Redis com proteção contra *stampede* (Anexo E).

Chave: ``busca:<versao>:<sha256(querystring normalizada)>`` (TTL 300 s).
``busca:versao`` é incrementado a cada publicação => invalida todo o cache de uma vez.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from urllib.parse import urlencode

from django.conf import settings

from tcc_common.cache.redis import adquirir_lock, get_redis, liberar_lock

logger = logging.getLogger(__name__)

CHAVE_VERSAO = "busca:versao"


def normalizar_querystring(params) -> str:
    """lowercase, parâmetros ordenados, espaços extras removidos, vazios descartados."""
    pares = []
    for chave in sorted(params.keys()):
        for valor in params.getlist(chave) if hasattr(params, "getlist") else [params[chave]]:
            valor = " ".join(str(valor).lower().split())
            if valor:
                pares.append((chave.lower(), valor))
    return urlencode(pares)


def chave_busca(params) -> tuple[str, str]:
    h = hashlib.sha256(normalizar_querystring(params).encode()).hexdigest()
    try:
        versao = get_redis().get(CHAVE_VERSAO) or "0"
    except Exception:  # noqa: BLE001
        versao = "0"
    return f"busca:{versao}:{h}", h


def invalidar_cache_busca() -> None:
    try:
        get_redis().incr(CHAVE_VERSAO)
    except Exception as exc:  # noqa: BLE001
        logger.warning("falha_invalidar_cache", extra={"erro": repr(exc)})


def obter_ou_calcular(params, calcular: Callable[[], dict], espera_max_s: float = 2.0) -> tuple[dict, str]:
    """Retorna (dados, "HIT"|"MISS"). Redis indisponível => calcula direto (degradação graciosa)."""
    if not settings.BUSCA_CACHE_ATIVO:
        return calcular(), "BYPASS"
    try:
        r = get_redis()
        chave, h = chave_busca(params)
        bruto = r.get(chave)
        if bruto:
            return json.loads(bruto), "HIT"
        lock = f"busca_lock:{h}"
        if adquirir_lock(lock, "1", 5):
            try:
                dados = calcular()
                r.set(chave, json.dumps(dados, default=str), ex=settings.BUSCA_CACHE_TTL_S)
                return dados, "MISS"
            finally:
                liberar_lock(lock)
        # outro worker está calculando a mesma busca: aguarda o resultado ficar pronto
        fim = time.monotonic() + espera_max_s
        while time.monotonic() < fim:
            time.sleep(0.05)
            bruto = r.get(chave)
            if bruto:
                return json.loads(bruto), "HIT"
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache_busca_indisponivel", extra={"erro": repr(exc)})
    return calcular(), "MISS"

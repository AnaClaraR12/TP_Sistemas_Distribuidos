"""Validação local de JWT RS256 (seção 4.4).

A chave pública é obtida, nesta ordem: ``JWT_PUBLIC_KEY`` (PEM no env) →
``JWT_PUBLIC_KEY_PATH`` (arquivo/secret) → JWKS do auth-service (``JWKS_URL``),
cacheado no Redis em ``jwks:cache`` por 1 h. Nenhuma chamada ao auth-service é feita
por requisição.
"""

from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from pathlib import Path

import jwt
import requests
from django.conf import settings
from jwt.algorithms import RSAAlgorithm

from tcc_common.cache.redis import get_redis

logger = logging.getLogger(__name__)

ALGORITMO = "RS256"
CHAVE_JWKS = "jwks:cache"
PREFIXO_REVOGADO = "jwt:revogado:"


class TokenInvalido(Exception):
    """Token ausente, malformado, expirado, revogado ou com assinatura inválida."""


@lru_cache(maxsize=1)
def _chave_publica_local() -> str | None:
    pem = getattr(settings, "JWT_PUBLIC_KEY", "") or ""
    if pem.strip():
        return pem.replace("\\n", "\n")
    caminho = getattr(settings, "JWT_PUBLIC_KEY_PATH", "") or ""
    if caminho and Path(caminho).exists():
        return Path(caminho).read_text()
    return None


def _chave_publica_jwks() -> str:
    r = get_redis()
    bruto = r.get(CHAVE_JWKS)
    if not bruto:
        url = settings.JWKS_URL
        resp = requests.get(url, timeout=3)
        resp.raise_for_status()
        bruto = resp.text
        r.set(CHAVE_JWKS, bruto, ex=3600)
    jwks = json.loads(bruto)
    chave = RSAAlgorithm.from_jwk(json.dumps(jwks["keys"][0]))
    from cryptography.hazmat.primitives import serialization

    return chave.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def obter_chave_publica() -> str:
    chave = _chave_publica_local()
    if chave:
        return chave
    try:
        return _chave_publica_jwks()
    except Exception as exc:  # noqa: BLE001
        logger.error("jwks_indisponivel", extra={"erro": str(exc)})
        raise TokenInvalido("Chave pública indisponível.") from exc


def token_revogado(jti: str) -> bool:
    try:
        return bool(get_redis().exists(PREFIXO_REVOGADO + jti))
    except Exception:  # noqa: BLE001
        # Redis fora: por padrão falha FECHADA (trata como revogado). Configurável.
        logger.warning("redis_indisponivel_checagem_revogacao")
        return not getattr(settings, "JWT_REVOGACAO_FAIL_OPEN", False)


def revogar_jti(jti: str, exp: int) -> None:
    ttl = max(int(exp - time.time()), 1)
    get_redis().set(PREFIXO_REVOGADO + jti, "1", ex=ttl)


def decodificar_token(token: str, tipo: str = "access") -> dict:
    """Valida assinatura, expiração, emissor, tipo e revogação. Retorna os claims."""
    if not token:
        raise TokenInvalido("Token ausente.")
    try:
        claims = jwt.decode(
            token,
            obter_chave_publica(),
            algorithms=[ALGORITMO],
            issuer=getattr(settings, "JWT_ISSUER", "auth-service"),
            options={"require": ["exp", "iat", "jti", "sub"]},
            leeway=5,
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenInvalido("Token expirado.") from exc
    except jwt.PyJWTError as exc:
        raise TokenInvalido("Token inválido.") from exc
    if claims.get("tipo") != tipo:
        raise TokenInvalido("Tipo de token inválido.")
    if token_revogado(claims["jti"]):
        raise TokenInvalido("Token revogado.")
    return claims

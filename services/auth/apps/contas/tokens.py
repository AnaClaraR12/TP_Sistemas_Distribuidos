"""Emissão de JWT RS256 (access 15 min, refresh 7 dias) e JWKS."""

import base64
import hashlib
import json
import time
import uuid
from functools import lru_cache
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from django.conf import settings
from jwt.algorithms import RSAAlgorithm

from tcc_common.auth.jwt import ALGORITMO, obter_chave_publica


class ChaveIndisponivel(RuntimeError):
    pass


@lru_cache(maxsize=1)
def chave_privada() -> str:
    pem = (settings.JWT_PRIVATE_KEY or "").replace("\\n", "\n")
    if pem.strip():
        return pem
    caminho = Path(settings.JWT_PRIVATE_KEY_PATH or "")
    if caminho.is_file():
        return caminho.read_text()
    raise ChaveIndisponivel("Chave privada JWT não configurada (JWT_PRIVATE_KEY ou JWT_PRIVATE_KEY_PATH).")


def _kid(pem_publico: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(pem_publico.encode()).digest()[:12]).decode().rstrip("=")


def claims_do_usuario(user) -> dict:
    """Claims de domínio: papel, aluno_id/professor_id e cursos do usuário."""
    aluno = getattr(user, "aluno", None) if hasattr(user, "aluno") else None
    professor = getattr(user, "professor", None) if hasattr(user, "professor") else None
    curso_ids: list[str] = []
    if aluno:
        curso_ids = [str(aluno.curso_id)]
    elif professor:
        curso_ids = [str(c) for c in professor.cursos_coordenados.values_list("id", flat=True)]
    return {
        "email": user.email,
        "nome": user.nome,
        "papel": user.papel,
        "aluno_id": str(aluno.id) if aluno else None,
        "professor_id": str(professor.id) if professor else None,
        "curso_ids": curso_ids,
    }


def _assinar(payload: dict) -> str:
    return jwt.encode(payload, chave_privada(), algorithm=ALGORITMO, headers={"kid": _kid(obter_chave_publica())})


def emitir_tokens(user) -> dict:
    agora = int(time.time())
    base = {"sub": str(user.id), "iss": settings.JWT_ISSUER, "iat": agora}
    access_exp = agora + settings.JWT_ACCESS_MINUTOS * 60
    refresh_exp = agora + settings.JWT_REFRESH_DIAS * 86400
    access = _assinar({**base, **claims_do_usuario(user), "tipo": "access", "exp": access_exp, "jti": uuid.uuid4().hex})
    refresh = _assinar({**base, "tipo": "refresh", "exp": refresh_exp, "jti": uuid.uuid4().hex})
    return {
        "access": access,
        "refresh": refresh,
        "token_type": "Bearer",
        "expires_in": settings.JWT_ACCESS_MINUTOS * 60,
    }


def jwks() -> dict:
    pem = obter_chave_publica()
    chave = serialization.load_pem_public_key(pem.encode())
    jwk = json.loads(RSAAlgorithm.to_jwk(chave))
    jwk.update({"kid": _kid(pem), "use": "sig", "alg": ALGORITMO})
    return {"keys": [jwk]}

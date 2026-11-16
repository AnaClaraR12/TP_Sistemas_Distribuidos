"""Plugin pytest compartilhado: ``pytest_plugins = ["tcc_common.testing"]``.

Fornece chaves JWT de teste, clientes autenticados por papel, Redis falso e helpers
para inspecionar o outbox e montar envelopes de eventos.
"""

import time
import uuid
from dataclasses import dataclass

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_CHAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
CHAVE_PRIVADA_PEM = _CHAVE.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
CHAVE_PUBLICA_PEM = (
    _CHAVE.public_key()
    .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    .decode()
)


def emitir_token_teste(papel: str = "aluno", *, tipo: str = "access", expira_em: int = 900, **claims) -> str:
    agora = int(time.time())
    payload = {
        "sub": claims.pop("sub", str(uuid.uuid4())),
        "email": claims.pop("email", f"{papel}@teste.br"),
        "papel": papel,
        "nome": claims.pop("nome", papel.title()),
        "tipo": tipo,
        "iss": "auth-service",
        "iat": agora,
        "exp": agora + expira_em,
        "jti": uuid.uuid4().hex,
        "curso_ids": claims.pop("curso_ids", []),
        **claims,
    }
    return jwt.encode(payload, CHAVE_PRIVADA_PEM, algorithm="RS256")


@dataclass
class Ator:
    """Usuário de teste: ids de domínio + cliente DRF autenticado."""

    papel: str
    user_id: str
    email: str
    aluno_id: str | None
    professor_id: str | None
    curso_ids: list[str]
    client: object
    token: str


@pytest.fixture(autouse=True)
def _configuracao_teste(settings, tmp_path):
    from tcc_common.auth import jwt as modjwt
    from tcc_common.cache.redis import get_redis, reset_redis

    settings.JWT_PUBLIC_KEY = CHAVE_PUBLICA_PEM
    settings.REDIS_URL = "fakeredis://"
    settings.SERVICE_TOKEN = "token-servico-teste"
    settings.MEDIA_ROOT = str(tmp_path / "media")
    settings.READY_CHECK_RABBITMQ = False
    from django.core.cache import caches

    modjwt._chave_publica_local.cache_clear()
    reset_redis()
    get_redis().flushall()
    for alias in settings.CACHES:
        caches[alias].clear()
    yield
    modjwt._chave_publica_local.cache_clear()


@pytest.fixture
def api():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def ator():
    """Fábrica: ``ator("aluno")``, ``ator("professor", professor_id=...)``."""
    from rest_framework.test import APIClient

    def _fabrica(papel: str = "aluno", **kw) -> Ator:
        user_id = kw.pop("user_id", str(uuid.uuid4()))
        email = kw.pop("email", f"{papel}-{user_id[:6]}@teste.br")
        aluno_id = kw.pop("aluno_id", str(uuid.uuid4()) if papel == "aluno" else None)
        professor_id = kw.pop("professor_id", str(uuid.uuid4()) if papel in ("professor", "coordenador") else None)
        curso_ids = [str(c) for c in kw.pop("curso_ids", [])]
        token = emitir_token_teste(
            papel,
            sub=user_id,
            email=email,
            aluno_id=str(aluno_id) if aluno_id else None,
            professor_id=str(professor_id) if professor_id else None,
            curso_ids=curso_ids,
            **kw,
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return Ator(
            papel,
            user_id,
            email,
            aluno_id and str(aluno_id),
            professor_id and str(professor_id),
            curso_ids,
            client,
            token,
        )

    return _fabrica


@pytest.fixture
def servico_client():
    from rest_framework.test import APIClient

    c = APIClient()
    c.credentials(HTTP_X_SERVICE_TOKEN="token-servico-teste")
    return c


def eventos_outbox(tipo: str | None = None) -> list[dict]:
    from tcc_common.events.models import OutboxEvento

    qs = OutboxEvento.objects.order_by("criado_em")
    if tipo:
        qs = qs.filter(tipo=tipo)
    return [e.payload for e in qs]


def envelope(tipo: str, data: dict, **kw) -> dict:
    from tcc_common.events.outbox import criar_envelope

    return criar_envelope(tipo, data, **kw)


def casar_routing_key(padrao: str, chave: str) -> bool:
    """Imita o exchange topic do RabbitMQ (``*`` = uma palavra, ``#`` = zero ou mais).

    Em produção quem roteia é o broker; aqui serve para os testes chamarem o handler
    certo a partir do tipo do evento, sem RabbitMQ.
    """
    p, c = padrao.split("."), chave.split(".")

    def casa(i: int, j: int) -> bool:
        if i == len(p):
            return j == len(c)
        if p[i] == "#":
            return any(casa(i + 1, k) for k in range(j, len(c) + 1))
        if j == len(c):
            return False
        return (p[i] == "*" or p[i] == c[j]) and casa(i + 1, j + 1)

    return casa(0, 0)


def encontrar_handler(handlers: dict, tipo: str):
    for padrao, handler in handlers.items():
        if casar_routing_key(padrao, tipo):
            return handler
    return None

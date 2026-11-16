"""JWT, usuário do token e permissões por papel."""

import pytest
import requests
from rest_framework.test import APIRequestFactory

from tcc_common.auth import jwt as modjwt
from tcc_common.auth.jwt import TokenInvalido, decodificar_token
from tcc_common.auth.permissions import IsAdmin, IsAutenticado, IsCoordenador, IsServicoInterno, papeis
from tcc_common.auth.usuario import UsuarioToken
from tcc_common.testing import emitir_token_teste

pytestmark = pytest.mark.django_db


def _request(usuario=None, **headers):
    req = APIRequestFactory().get("/", **headers)
    if usuario is not None:
        req.user = usuario
    return req


def _usuario(papel):
    return UsuarioToken(id="u1", email=f"{papel}@x", papel=papel)


def test_token_expirado_e_tipo_errado():
    with pytest.raises(TokenInvalido, match="expirado"):
        decodificar_token(emitir_token_teste("aluno", expira_em=-60))
    with pytest.raises(TokenInvalido, match="Tipo"):
        decodificar_token(emitir_token_teste("aluno", tipo="refresh"))
    with pytest.raises(TokenInvalido, match="ausente"):
        decodificar_token("")


def test_token_revogado():
    token = emitir_token_teste("aluno")
    claims = decodificar_token(token)
    modjwt.revogar_jti(claims["jti"], claims["exp"])
    with pytest.raises(TokenInvalido, match="revogado"):
        decodificar_token(token)


def test_jwks_fora_do_ar_vira_token_invalido(settings, monkeypatch):
    settings.JWT_PUBLIC_KEY = ""
    settings.JWT_PUBLIC_KEY_PATH = ""
    modjwt._chave_publica_local.cache_clear()

    def fora(*args, **kwargs):
        raise requests.ConnectionError("auth-service fora")

    monkeypatch.setattr(modjwt.requests, "get", fora)
    with pytest.raises(TokenInvalido, match="Chave pública indisponível"):
        decodificar_token(emitir_token_teste("aluno"))


def test_usuario_de_claims():
    u = UsuarioToken.de_claims(
        {"sub": "1", "email": "a@x", "papel": "aluno", "aluno_id": "a1", "curso_ids": ["c1"], "exp": 10}
    )
    assert (u.pk, u.aluno_id, u.professor_id, u.curso_ids, u.exp) == ("1", "a1", None, ("c1",), 10)
    assert str(u) == "a@x (aluno)"


@pytest.mark.parametrize(
    "permissao, papel, esperado",
    [
        (IsAdmin, "admin", True),
        (IsAdmin, "coordenador", False),
        (IsCoordenador, "coordenador", True),
        (IsCoordenador, "admin", True),
        (IsCoordenador, "professor", False),
        (papeis("aluno", "admin"), "aluno", True),
        (papeis("aluno", "admin"), "professor", False),
        (IsAutenticado, "aluno", True),
    ],
)
def test_permissoes_por_papel(permissao, papel, esperado):
    assert permissao().has_permission(_request(_usuario(papel)), None) is esperado


def test_anonimo_nao_tem_papel():
    from django.contrib.auth.models import AnonymousUser

    req = _request(AnonymousUser())
    assert IsAutenticado().has_permission(req, None) is False
    assert IsAdmin().has_permission(req, None) is False


def test_token_de_servico_vazio_nunca_libera(settings):
    settings.SERVICE_TOKEN = ""
    assert IsServicoInterno().has_permission(_request(HTTP_X_SERVICE_TOKEN=""), None) is False
    settings.SERVICE_TOKEN = "abc"
    assert IsServicoInterno().has_permission(_request(HTTP_X_SERVICE_TOKEN="abc"), None) is True
    assert IsServicoInterno().has_permission(_request(HTTP_X_SERVICE_TOKEN="abd"), None) is False

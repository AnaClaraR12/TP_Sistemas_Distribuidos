"""Login, bloqueio por tentativas, política de senha, JWT, refresh e logout."""

import time

import jwt as pyjwt
import pytest
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from tcc_common.auth.jwt import decodificar_token
from tcc_common.testing import CHAVE_PRIVADA_PEM, emitir_token_teste

from .conftest import SENHA_FORTE

pytestmark = pytest.mark.django_db


class TestPoliticaSenha:
    @pytest.mark.parametrize(
        "senha",
        [
            "curta@A1",
            "somenteminusculas123!",
            "SOMENTEMAIUSCULAS123!",
            "SemDigitosAqui!!",
            "SemSimbolo12345A",
            "123456789012345",
        ],
    )
    def test_senha_fraca_rejeitada(self, senha):
        with pytest.raises(ValidationError):
            validate_password(senha)

    def test_senha_similar_ao_email_rejeitada(self, criar_usuario):
        u = criar_usuario(email="mariasilva@ufvjm.edu.br")
        with pytest.raises(ValidationError):
            validate_password("Mariasilva@ufvjm1", user=u)

    def test_senha_forte_aceita(self):
        validate_password(SENHA_FORTE)

    def test_hash_argon2(self, criar_usuario):
        u = criar_usuario()
        assert u.password.startswith("argon2$")


class TestLogin:
    def test_login_ok_retorna_access_e_refresh(self, api, criar_usuario):
        criar_usuario("professor", email="prof@ufvjm.edu.br")
        r = api.post("/api/auth/token/", {"email": "prof@ufvjm.edu.br", "password": SENHA_FORTE}, format="json")
        assert r.status_code == 200
        claims = decodificar_token(r.data["access"])
        assert claims["papel"] == "professor"
        assert claims["email"] == "prof@ufvjm.edu.br"
        assert claims["exp"] - claims["iat"] == 15 * 60
        assert pyjwt.get_unverified_header(r.data["access"])["alg"] == "RS256"
        refresh = decodificar_token(r.data["refresh"], tipo="refresh")
        assert refresh["exp"] - refresh["iat"] == 7 * 86400

    def test_login_email_case_insensitive(self, api, criar_usuario):
        criar_usuario(email="ana@ufvjm.edu.br")
        r = api.post("/api/auth/token/", {"email": "ANA@ufvjm.edu.br", "password": SENHA_FORTE}, format="json")
        assert r.status_code == 200

    def test_login_falha(self, api, criar_usuario):
        criar_usuario(email="ana@ufvjm.edu.br")
        r = api.post("/api/auth/token/", {"email": "ana@ufvjm.edu.br", "password": "errada"}, format="json")
        assert r.status_code == 401
        assert r.data["codigo"] == "credenciais_invalidas"

    def test_usuario_inativo_nao_loga(self, api, criar_usuario):
        criar_usuario(email="ina@ufvjm.edu.br", is_active=False)
        r = api.post("/api/auth/token/", {"email": "ina@ufvjm.edu.br", "password": SENHA_FORTE}, format="json")
        assert r.status_code == 401

    def test_bloqueio_apos_5_falhas(self, api, criar_usuario):
        criar_usuario(email="ana@ufvjm.edu.br")
        for _ in range(5):
            api.post("/api/auth/token/", {"email": "ana@ufvjm.edu.br", "password": "errada"}, format="json")
        r = api.post("/api/auth/token/", {"email": "ana@ufvjm.edu.br", "password": SENHA_FORTE}, format="json")
        assert r.status_code == 429
        assert r.data["codigo"] == "conta_bloqueada"
        assert int(r["Retry-After"]) > 0

    def test_sucesso_zera_contador(self, api, criar_usuario):
        from tcc_common.cache.redis import get_redis

        criar_usuario(email="ana@ufvjm.edu.br")
        for _ in range(3):
            api.post("/api/auth/token/", {"email": "ana@ufvjm.edu.br", "password": "errada"}, format="json")
        assert get_redis().get("login_falhas:ana@ufvjm.edu.br") == "3"
        api.post("/api/auth/token/", {"email": "ana@ufvjm.edu.br", "password": SENHA_FORTE}, format="json")
        assert get_redis().get("login_falhas:ana@ufvjm.edu.br") is None

    def test_login_registra_auditoria_e_ip(self, api, criar_usuario):
        from apps.auditoria.models import RegistroAuditoria

        u = criar_usuario(email="ana@ufvjm.edu.br")
        api.post(
            "/api/auth/token/",
            {"email": "ana@ufvjm.edu.br", "password": SENHA_FORTE},
            format="json",
            REMOTE_ADDR="10.1.2.3",
        )
        api.post("/api/auth/token/", {"email": "ana@ufvjm.edu.br", "password": "x"}, format="json")
        assert RegistroAuditoria.objects.filter(acao="login", usuario_id=u.id, ip="10.1.2.3").exists()
        assert RegistroAuditoria.objects.filter(acao="login_falhou").exists()
        u.refresh_from_db()
        assert u.ultimo_login_ip == "10.1.2.3"


class TestJWT:
    def test_me_com_token_valido(self, criar_usuario, logar):
        criar_usuario(email="ana@ufvjm.edu.br", nome="Ana")
        c = logar("ana@ufvjm.edu.br")
        r = c.get("/api/auth/me/")
        assert r.status_code == 200
        assert r.data["email"] == "ana@ufvjm.edu.br"

    def test_token_expirado(self, api):
        token = emitir_token_teste("aluno", expira_em=-60)
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        r = api.get("/api/auth/me/")
        assert r.status_code == 401

    def test_token_adulterado(self, api, criar_usuario, logar):
        criar_usuario(email="ana@ufvjm.edu.br")
        token = logar("ana@ufvjm.edu.br").tokens["access"]
        cab, corpo, ass = token.split(".")
        adulterado = f"{cab}.{corpo[:-4]}AAAA.{ass}"
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {adulterado}")
        assert api.get("/api/auth/me/").status_code == 401

    def test_token_assinado_com_outra_chave(self, api):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        outra = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        agora = int(time.time())
        token = pyjwt.encode(
            {
                "sub": "x",
                "iss": "auth-service",
                "iat": agora,
                "exp": agora + 60,
                "jti": "j",
                "tipo": "access",
                "papel": "admin",
            },
            outra,
            algorithm="RS256",
        )
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        assert api.get("/api/auth/me/").status_code == 401

    def test_refresh_nao_serve_como_access(self, api, criar_usuario, logar):
        criar_usuario(email="ana@ufvjm.edu.br")
        refresh = logar("ana@ufvjm.edu.br").tokens["refresh"]
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh}")
        assert api.get("/api/auth/me/").status_code == 401

    def test_refresh_rotaciona(self, api, criar_usuario, logar):
        criar_usuario(email="ana@ufvjm.edu.br")
        refresh = logar("ana@ufvjm.edu.br").tokens["refresh"]
        r1 = api.post("/api/auth/token/refresh/", {"refresh": refresh}, format="json")
        assert r1.status_code == 200 and r1.data["access"]
        r2 = api.post("/api/auth/token/refresh/", {"refresh": refresh}, format="json")
        assert r2.status_code == 401  # refresh antigo foi revogado

    def test_logout_revoga_access(self, criar_usuario, logar):
        criar_usuario(email="ana@ufvjm.edu.br")
        c = logar("ana@ufvjm.edu.br")
        assert c.post("/api/auth/logout/", {"refresh": c.tokens["refresh"]}, format="json").status_code == 204
        assert c.get("/api/auth/me/").status_code == 401
        from tcc_common.auth.jwt import TokenInvalido

        with pytest.raises(TokenInvalido):
            decodificar_token(c.tokens["refresh"], tipo="refresh")

    def test_jwks_permite_validar_token(self, api, criar_usuario, logar):
        import json

        from jwt.algorithms import RSAAlgorithm

        criar_usuario(email="ana@ufvjm.edu.br")
        token = logar("ana@ufvjm.edu.br").tokens["access"]
        r = api.get("/.well-known/jwks.json")
        assert r.status_code == 200
        chave = RSAAlgorithm.from_jwk(json.dumps(r.json()["keys"][0]))
        claims = pyjwt.decode(token, chave, algorithms=["RS256"], issuer="auth-service")
        assert claims["email"] == "ana@ufvjm.edu.br"

    def test_validacao_por_jwks_sem_chave_local(self, settings, api, criar_usuario, logar):
        """Simula outro serviço: sem chave local, busca o JWKS uma vez e cacheia no Redis."""
        import responses

        from apps.contas.tokens import jwks
        from tcc_common.auth import jwt as modjwt
        from tcc_common.cache.redis import get_redis

        criar_usuario(email="ana@ufvjm.edu.br")
        token = logar("ana@ufvjm.edu.br").tokens["access"]
        corpo = jwks()
        settings.JWT_PUBLIC_KEY = ""
        settings.JWT_PUBLIC_KEY_PATH = ""
        settings.JWKS_URL = "http://auth-service:8001/.well-known/jwks.json"
        modjwt._chave_publica_local.cache_clear()
        with responses.RequestsMock() as rsps:
            rsps.get(settings.JWKS_URL, json=corpo)
            assert decodificar_token(token)["email"] == "ana@ufvjm.edu.br"
            assert decodificar_token(token)["email"] == "ana@ufvjm.edu.br"
            assert len(rsps.calls) == 1  # segunda validação usou o cache
        assert get_redis().get("jwks:cache")

    def test_claims_de_aluno(self, criar_usuario, logar, curso_com_coordenador):
        from apps.academico.models import Aluno

        curso, prof, _ = curso_com_coordenador
        u = criar_usuario(email="aluno@ufvjm.edu.br")
        aluno = Aluno.objects.create(
            user=u, nome="Al", matricula="2026001", email=u.email, curso=curso, orientador_atual=prof
        )
        claims = decodificar_token(logar("aluno@ufvjm.edu.br").tokens["access"])
        assert claims["aluno_id"] == str(aluno.id)
        assert claims["curso_ids"] == [str(curso.id)]
        claims_c = decodificar_token(logar("coord@ufvjm.edu.br").tokens["access"])
        assert claims_c["professor_id"] == str(prof.id)
        assert claims_c["curso_ids"] == [str(curso.id)]


def test_dashboard_config_por_papel(ator):
    r = ator("aluno").client.get("/api/auth/me/dashboard-config/")
    assert r.status_code == 200
    assert "nova_monografia" in [m["id"] for m in r.data["menus"]]
    r = ator("coordenador").client.get("/api/auth/me/dashboard-config/")
    assert "grafico_por_curso" in r.data["widgets"]


def test_cadastro_publico_desabilitado(client):
    from apps.contas.adapters import ContaAdapter
    from apps.contas.models import User

    assert ContaAdapter().is_open_for_signup(None) is False
    client.post("/api/auth/contas/signup/", {"email": "novo@x.com", "password1": SENHA_FORTE, "password2": SENHA_FORTE})
    assert not User.objects.filter(email="novo@x.com").exists()


def test_chave_privada_ausente(settings):
    from apps.contas import tokens

    settings.JWT_PRIVATE_KEY = ""
    settings.JWT_PRIVATE_KEY_PATH = "/nao/existe.pem"
    tokens.chave_privada.cache_clear()
    with pytest.raises(tokens.ChaveIndisponivel):
        tokens.chave_privada()
    settings.JWT_PRIVATE_KEY = CHAVE_PRIVADA_PEM
    tokens.chave_privada.cache_clear()

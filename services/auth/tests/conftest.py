import pytest
from rest_framework.test import APIClient

from tcc_common.testing import CHAVE_PRIVADA_PEM

SENHA_FORTE = "Senha@Forte#2026"


@pytest.fixture(autouse=True)
def _chave_privada(settings):
    from apps.contas import tokens

    settings.JWT_PRIVATE_KEY = CHAVE_PRIVADA_PEM
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK}
    tokens.chave_privada.cache_clear()
    yield
    tokens.chave_privada.cache_clear()


@pytest.fixture
def criar_usuario(db):
    from apps.contas.models import User

    def _criar(papel="aluno", email=None, senha=SENHA_FORTE, **kw):
        email = email or f"{papel}{User.objects.count()}@ufvjm.edu.br"
        return User.objects.create_user(
            email=email, password=senha, papel=papel, nome=kw.pop("nome", papel.title()), **kw
        )

    return _criar


@pytest.fixture
def logar():
    """Faz login via POST /api/auth/token/ e devolve um APIClient autenticado."""

    def _logar(email, senha=SENHA_FORTE):
        c = APIClient()
        r = c.post("/api/auth/token/", {"email": email, "password": senha}, format="json")
        assert r.status_code == 200, r.content
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        c.tokens = r.data
        return c

    return _logar


@pytest.fixture
def curso_com_coordenador(db, criar_usuario):
    from apps.academico.models import Curso, Professor

    u = criar_usuario("coordenador", email="coord@ufvjm.edu.br")
    prof = Professor.objects.create(user=u, nome="Coord", email=u.email, departamento="DECOM")
    curso = Curso.objects.create(nome="Sistemas de Informação", codigo="SI", coordenador=prof)
    return curso, prof, u

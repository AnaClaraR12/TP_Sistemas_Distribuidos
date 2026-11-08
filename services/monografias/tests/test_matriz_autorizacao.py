"""Matriz de autorização (Anexo D) — endpoint restrito × papel -> status esperado."""

import pytest

from .conftest import arquivo_pdf

pytestmark = pytest.mark.django_db

PAPEIS = ["anonimo", "aluno_dono", "outro_aluno", "orientador", "outro_prof", "coord", "admin"]


def _cliente(cenario, api, papel):
    return (
        api
        if papel == "anonimo"
        else {
            "aluno_dono": cenario.aluno,
            "outro_aluno": cenario.outro_aluno,
            "orientador": cenario.orientador,
            "outro_prof": cenario.outro_prof,
            "coord": cenario.coord,
            "admin": cenario.admin,
        }[papel].client
    )


MATRIZ_RASCUNHO = {
    # (método, sufixo): status por papel, na ordem de PAPEIS
    ("get", ""): [401, 200, 403, 200, 403, 200, 200],
    ("patch", ""): [401, 200, 403, 403, 403, 403, 200],
    ("post", "arquivo/"): [401, 201, 403, 403, 403, 403, 201],
    ("post", "submeter/"): [401, 400, 403, 403, 403, 403, 400],
    ("get", "historico/"): [401, 200, 403, 200, 403, 200, 200],
}


@pytest.mark.parametrize("acao", list(MATRIZ_RASCUNHO))
@pytest.mark.parametrize("papel", PAPEIS)
def test_matriz_rascunho(cenario, criar_rascunho, api, acao, papel):
    mid = criar_rascunho()
    metodo, sufixo = acao
    cli = _cliente(cenario, api, papel)
    url = f"/api/monografias/{mid}/{sufixo}"
    if sufixo == "arquivo/":
        r = cli.post(url, {"arquivo": arquivo_pdf()}, format="multipart")
    elif metodo == "patch":
        r = cli.patch(url, {"titulo": "Novo"}, format="json")
    else:
        r = getattr(cli, metodo)(url)
    assert r.status_code == MATRIZ_RASCUNHO[acao][PAPEIS.index(papel)], (acao, papel, r.status_code)


MATRIZ_SUBMETIDA = {
    ("post", "aprovar-orientador/"): [401, 403, 403, 200, 403, 403, 200],
    ("post", "verificar-integridade/"): [401, 200, 403, 200, 403, 200, 200],
}


@pytest.mark.parametrize("acao", list(MATRIZ_SUBMETIDA))
@pytest.mark.parametrize("papel", PAPEIS)
def test_matriz_submetida(cenario, submetida, api, acao, papel):
    metodo, sufixo = acao
    r = getattr(_cliente(cenario, api, papel), metodo)(f"/api/monografias/{submetida}/{sufixo}")
    assert r.status_code == MATRIZ_SUBMETIDA[acao][PAPEIS.index(papel)], (acao, papel, r.status_code)


@pytest.mark.parametrize("papel,esperado", zip(PAPEIS, [401, 204, 403, 403, 403, 204, 204]))
def test_matriz_exclusao_rascunho(cenario, criar_rascunho, api, papel, esperado):
    mid = criar_rascunho()
    assert _cliente(cenario, api, papel).delete(f"/api/monografias/{mid}/").status_code == esperado


@pytest.mark.parametrize("papel,esperado", zip(PAPEIS, [401, 201, 201, 403, 403, 403, 201]))
def test_criar_monografia_por_papel(cenario, api, papel, esperado):
    """Alunos criam a própria; professor/coordenador não criam; admin cria informando aluno_id."""
    payload = {"titulo": "T", "orientador_id": str(cenario.orientador_ref.id), "aluno_id": str(cenario.aluno_ref.id)}
    r = _cliente(cenario, api, papel).post("/api/monografias/", payload, format="json")
    assert r.status_code == esperado


def test_nenhum_endpoint_restrito_responde_200_a_anonimo(api, cenario, criar_rascunho):
    from django.urls import get_resolver

    mid = criar_rascunho()
    for padrao in get_resolver().url_patterns:
        rota = str(padrao.pattern)
        if "api/monografias" not in rota:
            continue
        url = "/api/monografias/" if "<pk>" not in rota and "(?P<pk>" not in rota else f"/api/monografias/{mid}/"
        assert api.get(url).status_code in (401, 405), rota

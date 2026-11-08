"""Agendamento em 2 etapas, confirmações, conflitos, token externo, avaliações e resultado."""

import threading
import uuid
from datetime import timedelta

import pytest
import responses
from django.db import connection
from django.utils import timezone

from tcc_common.testing import envelope, eventos_outbox

from .conftest import PARECER, confirmar_todos, payload_banca, token_externo

pytestmark = pytest.mark.django_db


# --- etapa 1 -------------------------------------------------------------------------------


def test_criar_banca_inclui_orientador_e_gera_convites(cenario, criar_banca):
    from apps.bancas.models import MembroBanca

    b = criar_banca()
    assert b["status"] == "em_organizacao" and b["duracao_minutos"] == 120
    funcoes = {m["email"]: m["funcao"] for m in b["membros"]}
    assert funcoes["p0@ufvjm.edu.br"] == "orientador" and len(b["membros"]) == 3
    externo = MembroBanca.objects.get(email="externa@outra.edu.br")
    token = token_externo()
    assert externo.token_hash and externo.token_hash != token and len(externo.token_hash) == 64
    assert externo.token_expira_em == externo.banca.data_hora_inicio + timedelta(days=7)
    assert len(eventos_outbox("banca.convite_enviado")) == 3


def test_orientador_da_monografia_pode_criar(cenario, criar_banca):
    assert criar_banca(cliente=cenario.orientador.client)["status"] == "em_organizacao"


def test_professor_qualquer_nao_cria_403(cenario):
    r = cenario.p3.client.post("/api/bancas/", payload_banca(cenario), format="json")
    assert r.status_code == 403
    assert cenario.aluno.client.post("/api/bancas/", payload_banca(cenario), format="json").status_code == 403


def test_sem_aprovacao_do_orientador_409(cenario):
    from apps.bancas.models import MonografiaRef

    MonografiaRef.objects.filter(pk=cenario.mono.pk).update(aprovacao_orientador="pendente")
    with responses.RequestsMock() as rsps:  # fallback HTTP confirma que continua pendente
        rsps.get(
            f"http://monografias-service:8002/internal/monografias/{cenario.mono.id}/",
            json={
                "id": str(cenario.mono.id),
                "titulo": "TCC",
                "status": "em_avaliacao",
                "aprovacao_orientador": "pendente",
                "aluno_id": None,
                "orientador_id": str(cenario.profs[0].id),
                "curso_id": None,
            },
        )
        r = cenario.coord.client.post("/api/bancas", payload_banca(cenario), format="json")
    assert r.status_code == 409 and r.data["codigo"] == "orientador_nao_aprovou"


def test_read_model_ausente_usa_http_interno(cenario):
    mid = uuid.uuid4()
    with responses.RequestsMock() as rsps:
        rsps.get(
            f"http://monografias-service:8002/internal/monografias/{mid}/",
            json={
                "id": str(mid),
                "titulo": "Outro",
                "status": "em_avaliacao",
                "aprovacao_orientador": "aprovada",
                "aluno_id": None,
                "orientador_id": str(cenario.profs[0].id),
                "curso_id": str(cenario.curso_id),
            },
        )
        r = cenario.coord.client.post("/api/bancas/", payload_banca(cenario, monografia_id=mid), format="json")
        assert rsps.calls[0].request.headers["X-Service-Token"] == "token-servico-teste"
    assert r.status_code == 201


@pytest.mark.parametrize("local,link", [("Sala 1", "https://meet.x/abc"), (None, None), ("", "")])
def test_exatamente_um_entre_local_e_link(cenario, local, link):
    r = cenario.coord.client.post("/api/bancas/", payload_banca(cenario, local=local, link=link), format="json")
    assert r.status_code == 400


def test_banca_remota_com_link(cenario):
    r = cenario.coord.client.post(
        "/api/bancas/", payload_banca(cenario, local=None, link="https://meet.ufvjm.br/tcc"), format="json"
    )
    assert r.status_code == 201 and r.data["link"] and r.data["local"] is None


def test_minimo_3_membros(cenario):
    r = cenario.coord.client.post(
        "/api/bancas/",
        payload_banca(cenario, membros=[{"tipo": "interno", "professor_id": str(cenario.profs[1].id)}]),
        format="json",
    )
    assert r.status_code == 400 and r.data["codigo"] == "membros_insuficientes"


# --- etapa 2 -------------------------------------------------------------------------------


def test_agendar_sem_todas_confirmacoes_409(cenario, criar_banca):
    b = criar_banca()
    r = cenario.coord.client.post(f"/api/bancas/{b['id']}/agendar/")
    assert r.status_code == 409 and r.data["codigo"] == "confirmacoes_pendentes"
    assert len(r.data["detalhes"]["membros"]) == 3


def test_agendar_ok_publica_evento_com_todos(cenario, criar_banca, api):
    b = criar_banca()
    confirmar_todos(cenario, b, api)
    r = cenario.coord.client.post(f"/api/bancas/{b['id']}/agendar/")
    assert r.status_code == 200 and r.data["status"] == "agendada"
    ev = eventos_outbox("banca.agendada")[-1]["data"]
    assert ev["aluno_id"] == str(cenario.mono.aluno_id)
    assert {m["email"] for m in ev["membros"]} == {"p0@ufvjm.edu.br", "p1@ufvjm.edu.br", "externa@outra.edu.br"}


def test_agendar_se_monografia_perdeu_aprovacao_409(cenario, criar_banca, api):
    from apps.bancas.models import MonografiaRef

    b = criar_banca()
    confirmar_todos(cenario, b, api)
    MonografiaRef.objects.filter(pk=cenario.mono.pk).update(status="rascunho", aprovacao_orientador="rejeitada")
    with responses.RequestsMock() as rsps:
        rsps.get(f"http://monografias-service:8002/internal/monografias/{cenario.mono.id}/", status=404)
        r = cenario.coord.client.post(f"/api/bancas/{b['id']}/agendar/")
    assert r.status_code in (404, 409)


def test_recusa_e_substituicao_de_membro(cenario, criar_banca, api):
    b = criar_banca()
    m1 = next(m for m in b["membros"] if m["professor_id"] == str(cenario.profs[1].id))
    r = cenario.p1.client.post(
        f"/api/bancas/{b['id']}/membros/{m1['id']}/confirmar/", {"resposta": "recusado"}, format="json"
    )
    assert r.data["confirmacao"] == "recusado"
    assert cenario.coord.client.delete(f"/api/bancas/{b['id']}/membros/{m1['id']}/").status_code == 204
    r = cenario.coord.client.post(
        f"/api/bancas/{b['id']}/membros/", {"tipo": "interno", "professor_id": str(cenario.profs[2].id)}, format="json"
    )
    assert r.status_code == 201
    b = cenario.coord.client.get(f"/api/bancas/{b['id']}/").data
    confirmar_todos(cenario, b, api)
    assert cenario.coord.client.post(f"/api/bancas/{b['id']}/agendar/").status_code == 200


def test_confirmar_por_outro_professor_403(cenario, criar_banca):
    b = criar_banca()
    m1 = next(m for m in b["membros"] if m["professor_id"] == str(cenario.profs[1].id))
    assert cenario.p2.client.post(f"/api/bancas/{b['id']}/membros/{m1['id']}/confirmar/").status_code == 403


def _segunda_monografia(cenario):
    from apps.bancas.models import MonografiaRef

    return MonografiaRef.objects.create(
        id=uuid.uuid4(),
        titulo="TCC 2",
        status="em_avaliacao",
        aprovacao_orientador="aprovada",
        aluno_id=uuid.uuid4(),
        orientador_id=cenario.profs[3].id,
        curso_id=cenario.curso_id,
    )


def test_conflito_de_horario_409(cenario, criar_banca, api):
    inicio = (timezone.now() + timedelta(days=5)).replace(microsecond=0, second=0)
    b1 = criar_banca(inicio=inicio)
    confirmar_todos(cenario, b1, api)
    assert cenario.coord.client.post(f"/api/bancas/{b1['id']}/agendar/").status_code == 200
    mono2 = _segunda_monografia(cenario)
    # mesmo prof 1, começando 1h depois (sobrepõe as 2h da primeira)
    b2 = cenario.coord.client.post(
        "/api/bancas/",
        payload_banca(cenario, inicio=inicio + timedelta(hours=1), monografia_id=mono2.id, externo=False),
        format="json",
    ).data
    confirmar_todos(cenario, b2, api)
    r = cenario.coord.client.post(f"/api/bancas/{b2['id']}/agendar/")
    assert r.status_code == 409 and r.data["codigo"] == "conflito_horario"
    assert r.data["detalhes"]["conflitos"][0]["banca_id"] == b1["id"]


def test_sem_conflito_quando_horarios_nao_sobrepoem(cenario, criar_banca, api):
    inicio = (timezone.now() + timedelta(days=5)).replace(microsecond=0, second=0)
    b1 = criar_banca(inicio=inicio)
    confirmar_todos(cenario, b1, api)
    cenario.coord.client.post(f"/api/bancas/{b1['id']}/agendar/")
    mono2 = _segunda_monografia(cenario)
    b2 = cenario.coord.client.post(
        "/api/bancas/",
        payload_banca(cenario, inicio=inicio + timedelta(hours=2), monografia_id=mono2.id, externo=False),
        format="json",
    ).data
    confirmar_todos(cenario, b2, api)
    assert cenario.coord.client.post(f"/api/bancas/{b2['id']}/agendar/").status_code == 200


def test_conflito_de_membro_externo_por_email(cenario, criar_banca, api):
    inicio = (timezone.now() + timedelta(days=5)).replace(microsecond=0, second=0)
    b1 = criar_banca(inicio=inicio)
    confirmar_todos(cenario, b1, api)
    cenario.coord.client.post(f"/api/bancas/{b1['id']}/agendar/")
    mono2 = _segunda_monografia(cenario)
    b2 = cenario.coord.client.post(
        "/api/bancas/",
        payload_banca(
            cenario,
            inicio=inicio + timedelta(minutes=30),
            monografia_id=mono2.id,
            membros=[
                {"tipo": "interno", "professor_id": str(cenario.profs[2].id)},
                {"tipo": "externo", "nome": "Dra. Externa", "email": "EXTERNA@outra.edu.br"},
            ],
        ),
        format="json",
    ).data
    confirmar_todos(cenario, b2, api)
    assert cenario.coord.client.post(f"/api/bancas/{b2['id']}/agendar/").status_code == 409


# --- edição / cancelamento ------------------------------------------------------------------


def test_editar_horario_exige_reconfirmacao(cenario, criar_banca, api):
    b = criar_banca()
    confirmar_todos(cenario, b, api)
    cenario.coord.client.post(f"/api/bancas/{b['id']}/agendar/")
    novo = (timezone.now() + timedelta(days=20)).replace(microsecond=0).isoformat()
    r = cenario.coord.client.patch(f"/api/bancas/{b['id']}/", {"data_hora_inicio": novo}, format="json")
    assert r.status_code == 200 and r.data["status"] == "em_organizacao"
    assert all(m["confirmacao"] == "pendente" for m in r.data["membros"])


def test_nao_edita_banca_realizada(cenario, banca_realizada):
    r = cenario.coord.client.patch(f"/api/bancas/{banca_realizada['id']}/", {"local": "Outra sala"}, format="json")
    assert r.status_code == 409 and r.data["codigo"] == "banca_nao_editavel"


def test_cancelar_revoga_tokens_e_notifica(cenario, criar_banca, api):
    b = criar_banca()
    token = token_externo()
    r = cenario.coord.client.post(
        f"/api/bancas/{b['id']}/cancelar/", {"motivo": "Aluno solicitou adiamento"}, format="json"
    )
    assert r.status_code == 200 and r.data["status"] == "cancelada"
    assert eventos_outbox("banca.cancelada")[-1]["data"]["motivo"] == "Aluno solicitou adiamento"
    r = api.get("/api/bancas/externo/minha-banca/", HTTP_X_BANCA_TOKEN=token)
    assert r.status_code == 401 and r.data["codigo"] == "token_revogado"


def test_excluir_somente_em_organizacao_ou_cancelada(cenario, banca_realizada, criar_banca):
    assert cenario.coord.client.delete(f"/api/bancas/{banca_realizada['id']}/").status_code == 409


# --- token externo ------------------------------------------------------------------------------


def test_token_externo_acessa_somente_sua_banca(cenario, criar_banca, api):
    b = criar_banca()
    token = token_externo()
    r = api.get("/api/bancas/externo/minha-banca/", HTTP_X_BANCA_TOKEN=token)
    assert r.status_code == 200 and r.data["banca"]["id"] == b["id"]
    assert "membros" not in r.data["banca"]  # dados mínimos
    # o token não serve como credencial das rotas autenticadas
    assert api.get(f"/api/bancas/{b['id']}/", HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 401
    assert api.get("/api/bancas/", HTTP_X_BANCA_TOKEN=token).status_code == 401


@pytest.mark.parametrize("caso", ["adulterado", "ausente", "expirado", "revogado"])
def test_token_externo_invalido(cenario, criar_banca, api, caso):
    from apps.bancas.models import MembroBanca

    criar_banca()
    token = token_externo()
    if caso == "adulterado":
        token = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    elif caso == "ausente":
        token = ""
    elif caso == "expirado":
        MembroBanca.objects.filter(tipo="externo").update(token_expira_em=timezone.now() - timedelta(minutes=1))
    else:
        MembroBanca.objects.filter(tipo="externo").update(token_revogado=True)
    r = api.post("/api/bancas/externo/confirmar/", {"resposta": "confirmado"}, format="json", HTTP_X_BANCA_TOKEN=token)
    assert r.status_code == 401


def test_rate_limit_por_ip_no_token_externo(cenario, criar_banca, api, settings):
    settings.EXTERNO_RATE_LIMIT_POR_MIN = 3
    criar_banca()
    for _ in range(3):
        api.get("/api/bancas/externo/minha-banca/", HTTP_X_BANCA_TOKEN="x")
    r = api.get("/api/bancas/externo/minha-banca/", HTTP_X_BANCA_TOKEN=token_externo())
    assert r.status_code == 429


def test_uso_do_token_e_auditado(cenario, criar_banca, api):
    criar_banca()
    api.get("/api/bancas/externo/minha-banca/", HTTP_X_BANCA_TOKEN=token_externo())
    acoes = [e["data"]["acao"] for e in eventos_outbox("audit.registro")]
    assert "token_externo_gerado" in acoes and "token_externo_usado" in acoes
    assert all("token" not in (e["data"].get("detalhes") or {}) for e in eventos_outbox("audit.registro"))


def test_pdf_por_url_assinada(cenario, criar_banca, api):
    criar_banca()
    r = api.get("/api/bancas/externo/minha-banca/", HTTP_X_BANCA_TOKEN=token_externo())
    url = r.data["pdf_url"]
    with responses.RequestsMock() as rsps:
        rsps.get(f"http://monografias-service:8002/internal/monografias/{cenario.mono.id}/arquivo/", body=b"%PDF-1.4 x")
        r = api.get(url)
        assert r.status_code == 200 and b"".join(r.streaming_content).startswith(b"%PDF")
    assert api.get(url[:-3] + "xyz").status_code == 403


# --- avaliações e resultado ---------------------------------------------------------------------


def _avaliar(cenario, banca, api, notas_recs):
    """notas_recs: lista (nota, recomendação) para orientador, prof 1 e externo, nesta ordem."""
    clientes = [cenario.orientador.client, cenario.p1.client, None]
    respostas = []
    for cli, (nota, rec) in zip(clientes, notas_recs):
        dados = {"nota": nota, "parecer": PARECER, "recomendacao": rec}
        if cli is None:
            r = api.post("/api/bancas/externo/avaliacao/", dados, format="json", HTTP_X_BANCA_TOKEN=token_externo())
        else:
            r = cli.post(f"/api/bancas/{banca['id']}/avaliacoes/", dados, format="json")
        respostas.append(r)
    return respostas


def _processar_eventos_avaliacao():
    from apps.bancas.eventos import HANDLERS
    from tcc_common.events.consumer import encontrar_handler, processar_evento

    for env in eventos_outbox("avaliacao.registrada"):
        processar_evento(env, encontrar_handler(HANDLERS, env["type"]))


def test_avaliacao_antes_da_realizacao_409(cenario, criar_banca, api):
    b = criar_banca()
    confirmar_todos(cenario, b, api)
    r = cenario.orientador.client.post(
        f"/api/bancas/{b['id']}/avaliacoes/",
        {"nota": 8, "parecer": PARECER, "recomendacao": "aprovado_sem_ressalvas"},
        format="json",
    )
    assert r.status_code == 409 and r.data["codigo"] == "banca_nao_realizada"


@pytest.mark.parametrize(
    "dados",
    [
        {"nota": "10.5", "parecer": PARECER, "recomendacao": "aprovado_sem_ressalvas"},
        {"nota": "-1", "parecer": PARECER, "recomendacao": "aprovado_sem_ressalvas"},
        {"nota": "8", "parecer": "curto demais", "recomendacao": "aprovado_sem_ressalvas"},
        {"nota": "8", "parecer": PARECER, "recomendacao": "talvez"},
        {"nota": "8.55", "parecer": PARECER, "recomendacao": "aprovado_sem_ressalvas"},
    ],
)
def test_avaliacao_validacoes(cenario, banca_realizada, dados):
    r = cenario.orientador.client.post(f"/api/bancas/{banca_realizada['id']}/avaliacoes/", dados, format="json")
    assert r.status_code == 400


def test_avaliacao_duplicada_409(cenario, banca_realizada, api):
    _avaliar(cenario, banca_realizada, api, [(8, "aprovado_sem_ressalvas")])
    r = _avaliar(cenario, banca_realizada, api, [(9, "aprovado_sem_ressalvas")])[0]
    assert r.status_code == 409 and r.data["codigo"] == "avaliacao_duplicada"


def test_nao_membro_nao_avalia(cenario, banca_realizada):
    r = cenario.p3.client.post(
        f"/api/bancas/{banca_realizada['id']}/avaliacoes/",
        {"nota": 8, "parecer": PARECER, "recomendacao": "aprovado_sem_ressalvas"},
        format="json",
    )
    assert r.status_code == 403


def test_resultado_nao_calculado_com_2_de_3(cenario, banca_realizada, api):
    from apps.bancas.models import Banca

    rs = _avaliar(cenario, banca_realizada, api, [(8, "aprovado_sem_ressalvas"), (7, "aprovado_sem_ressalvas")])
    assert all(r.status_code == 201 for r in rs)
    _processar_eventos_avaliacao()
    b = Banca.objects.get(pk=banca_realizada["id"])
    assert b.resultado_calculado_em is None and b.resultado_final is None
    assert not eventos_outbox("banca.resultado_calculado")


def test_resultado_aprovada_media(cenario, banca_realizada, api):
    from apps.bancas.models import Banca, MembroBanca

    _avaliar(
        cenario,
        banca_realizada,
        api,
        [(8, "aprovado_sem_ressalvas"), (7, "aprovado_sem_ressalvas"), (9.5, "aprovado_sem_ressalvas")],
    )
    _processar_eventos_avaliacao()
    b = Banca.objects.get(pk=banca_realizada["id"])
    assert b.resultado_final == "aprovada" and str(b.media_final) == "8.17" and b.exige_correcao is False
    ev = eventos_outbox("banca.resultado_calculado")[-1]["data"]
    assert ev["monografia_id"] == str(cenario.mono.id) and ev["resultado"] == "aprovada" and ev["media"] == "8.17"
    assert MembroBanca.objects.get(tipo="externo").token_revogado is True  # revogado ao fechar


def test_resultado_com_ressalvas_exige_correcao(cenario, banca_realizada, api):
    from apps.bancas.models import Banca

    _avaliar(
        cenario,
        banca_realizada,
        api,
        [(8, "aprovado_sem_ressalvas"), (7, "aprovado_com_ressalvas"), (8, "aprovado_sem_ressalvas")],
    )
    _processar_eventos_avaliacao()
    b = Banca.objects.get(pk=banca_realizada["id"])
    assert b.resultado_final == "aprovada" and b.exige_correcao is True


def test_resultado_maioria_reprovado(cenario, banca_realizada, api):
    from apps.bancas.models import Banca

    _avaliar(cenario, banca_realizada, api, [(9, "reprovado"), (9, "reprovado"), (9, "aprovado_sem_ressalvas")])
    _processar_eventos_avaliacao()
    assert Banca.objects.get(pk=banca_realizada["id"]).resultado_final == "reprovada"


def test_resultado_media_abaixo_de_6(cenario, banca_realizada, api):
    from apps.bancas.models import Banca

    _avaliar(
        cenario,
        banca_realizada,
        api,
        [(5, "aprovado_sem_ressalvas"), (6, "aprovado_sem_ressalvas"), (6.5, "aprovado_com_ressalvas")],
    )
    _processar_eventos_avaliacao()
    b = Banca.objects.get(pk=banca_realizada["id"])
    assert b.resultado_final == "reprovada" and b.exige_correcao is False


def test_calculo_idempotente(cenario, banca_realizada, api):
    from apps.bancas.servicos import calcular_resultado

    _avaliar(
        cenario,
        banca_realizada,
        api,
        [(8, "aprovado_sem_ressalvas"), (7, "aprovado_sem_ressalvas"), (9, "aprovado_sem_ressalvas")],
    )
    _processar_eventos_avaliacao()
    calcular_resultado(banca_realizada["id"])
    _processar_eventos_avaliacao()  # eventos repetidos
    env = envelope("avaliacao.registrada", {"banca_id": banca_realizada["id"], "avaliacao_id": "x", "membro_id": "y"})
    from apps.bancas.eventos import HANDLERS
    from tcc_common.events.consumer import encontrar_handler, processar_evento

    processar_evento(env, encontrar_handler(HANDLERS, env["type"]))
    assert len(eventos_outbox("banca.resultado_calculado")) == 1


def test_edicao_da_avaliacao_antes_e_depois_do_fechamento(cenario, banca_realizada, api):
    r = _avaliar(cenario, banca_realizada, api, [(8, "aprovado_sem_ressalvas")])[0]
    url = f"/api/bancas/{banca_realizada['id']}/avaliacoes/{r.data['id']}/"
    assert cenario.p1.client.patch(url, {"nota": 3}, format="json").status_code in (403, 404)  # não é o avaliador
    r2 = cenario.orientador.client.patch(url, {"nota": "9.0"}, format="json")
    assert r2.status_code == 200 and r2.data["nota"] == "9.0"
    r_p1 = cenario.p1.client.post(
        f"/api/bancas/{banca_realizada['id']}/avaliacoes/",
        {"nota": 7, "parecer": PARECER, "recomendacao": "aprovado_sem_ressalvas"},
        format="json",
    )
    assert r_p1.status_code == 201
    api_ext = api.post(
        "/api/bancas/externo/avaliacao/",
        {"nota": 8, "parecer": PARECER, "recomendacao": "aprovado_sem_ressalvas"},
        format="json",
        HTTP_X_BANCA_TOKEN=token_externo(),
    )
    assert api_ext.status_code == 201
    _processar_eventos_avaliacao()
    r3 = cenario.orientador.client.patch(url, {"nota": "5.0"}, format="json")
    assert r3.status_code == 409 and r3.data["codigo"] == "resultado_fechado"
    assert (
        cenario.orientador.client.patch(f"/api/avaliacoes/{r.data['id']}/", {"nota": 5}, format="json").status_code
        == 409
    )


def test_historico_da_avaliacao(cenario, banca_realizada, api):
    r = _avaliar(cenario, banca_realizada, api, [(8, "aprovado_sem_ressalvas")])[0]
    cenario.orientador.client.patch(f"/api/avaliacoes/{r.data['id']}/", {"nota": "9.0"}, format="json")
    h = cenario.orientador.client.get(f"/api/avaliacoes/{r.data['id']}/historico/").data["historico"]
    assert h[0]["usuario_id"] == cenario.orientador.user_id
    assert h[0]["alteracoes"][0]["campo"] == "nota"


def test_visibilidade(cenario, criar_banca):
    b = criar_banca()
    assert cenario.aluno.client.get("/api/bancas/").data["count"] == 1
    assert cenario.p1.client.get("/api/bancas/?minhas=1").data["count"] == 1
    assert cenario.p3.client.get("/api/bancas/").data["count"] == 0
    assert cenario.p3.client.get(f"/api/bancas/{b['id']}/").status_code == 403
    assert cenario.coord.client.get("/api/bancas/").data["count"] == 1


def test_consumer_read_model_monografia(cenario):
    from apps.bancas.eventos import HANDLERS
    from apps.bancas.models import MonografiaRef
    from tcc_common.events.consumer import encontrar_handler, processar_evento

    mid = str(uuid.uuid4())
    base = {
        "id": mid,
        "titulo": "Nova",
        "status": "em_avaliacao",
        "aprovacao_orientador": "aprovada",
        "aluno_id": None,
        "orientador_id": None,
        "curso_id": None,
    }
    env = envelope("monografia.aprovada_orientador", {**base, "sha256_aprovado": "abc"})
    processar_evento(env, encontrar_handler(HANDLERS, env["type"]))
    assert MonografiaRef.objects.get(pk=mid).apta_para_banca
    env = envelope("monografia.texto_extraido", {"id": mid, "paginas": 1, "sem_texto": False})
    processar_evento(env, encontrar_handler(HANDLERS, env["type"]))
    assert MonografiaRef.objects.get(pk=mid).titulo == "Nova"


@pytest.mark.django_db(transaction=True)
def test_agendamento_concorrente_sem_race_condition(ator):
    """Duas bancas com o mesmo membro e horário sobreposto agendadas ao mesmo tempo: só uma passa."""
    from apps.bancas import servicos
    from apps.bancas.models import Banca, MembroBanca, MonografiaRef

    inicio = timezone.now() + timedelta(days=3)
    comum = uuid.uuid4()
    bancas = []
    for i in range(2):
        mono = MonografiaRef.objects.create(
            id=uuid.uuid4(),
            titulo=f"T{i}",
            status="em_avaliacao",
            aprovacao_orientador="aprovada",
            orientador_id=uuid.uuid4(),
        )
        b = Banca.objects.create(monografia_id=mono.id, data_hora_inicio=inicio + timedelta(minutes=30 * i), local="S")
        MembroBanca.objects.create(
            banca=b, tipo="interno", professor_id=comum, nome="Comum", email="comum@x.br", confirmacao="confirmado"
        )
        MembroBanca.objects.create(
            banca=b,
            tipo="interno",
            professor_id=uuid.uuid4(),
            nome=f"O{i}",
            email=f"o{i}@x.br",
            confirmacao="confirmado",
        )
        bancas.append(b)
    admin = ator("admin")
    from tcc_common.auth.usuario import UsuarioToken

    usuario = UsuarioToken(id=admin.user_id, email="a@x", papel="admin")
    barreira = threading.Barrier(2)
    resultados = []

    def agendar(bid):
        try:
            barreira.wait()
            servicos.agendar(bid, usuario)
            resultados.append("ok")
        except Exception as exc:  # noqa: BLE001
            resultados.append(getattr(exc, "codigo", repr(exc)))
        finally:
            connection.close()

    threads = [threading.Thread(target=agendar, args=(b.id,)) for b in bancas]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(resultados) == ["conflito_horario", "ok"]
    assert Banca.objects.filter(status="agendada").count() == 1

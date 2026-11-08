"""CRUD, máquina de estados, aprovação, resultado de banca, integridade e publicação automática."""

import uuid

import pytest
from django.core.files.storage import default_storage

from tcc_common.cache.redis import get_redis
from tcc_common.testing import envelope, eventos_outbox

from .conftest import arquivo_pdf

pytestmark = pytest.mark.django_db


# --- CRUD ------------------------------------------------------------------------------


def test_criar_sem_barra_final_e_dados_do_jwt(cenario):
    r = cenario.aluno.client.post(
        "/api/monografias",
        {
            "titulo": "T",
            "resumo": "R",
            "palavras_chave": ["a", "b", "c"],
            "orientador_id": str(cenario.orientador_ref.id),
            "status": "publicada",
            "aluno_id": str(uuid.uuid4()),
        },
        format="json",
    )
    assert r.status_code == 201
    assert r.data["status"] == "rascunho"  # mass assignment ignorado
    assert r.data["aluno_id"] == str(cenario.aluno_ref.id)
    assert r.data["curso_id"] == str(cenario.curso.id)


def test_professor_nao_cria_monografia(cenario):
    r = cenario.orientador.client.post("/api/monografias/", {"titulo": "T"}, format="json")
    assert r.status_code == 403


def test_orientador_inexistente_400(cenario):
    r = cenario.aluno.client.post(
        "/api/monografias/", {"titulo": "T", "orientador_id": str(uuid.uuid4())}, format="json"
    )
    assert r.status_code == 400


def test_editar_rascunho_e_historico(cenario, criar_rascunho):
    mid = criar_rascunho()
    r = cenario.aluno.client.patch(f"/api/monografias/{mid}/", {"titulo": "Novo título"}, format="json")
    assert r.status_code == 200 and r.data["titulo"] == "Novo título"
    h = cenario.aluno.client.get(f"/api/monografias/{mid}/historico/").data["historico"]
    assert h[0]["usuario_id"] == cenario.aluno.user_id
    assert {"campo": "titulo", "anterior": "Sistemas distribuídos com microsserviços", "novo": "Novo título"} in h[0][
        "alteracoes"
    ]


def test_editar_fora_de_rascunho_409(cenario, submetida):
    r = cenario.aluno.client.patch(f"/api/monografias/{submetida}/", {"titulo": "X"}, format="json")
    assert r.status_code == 409 and r.data["codigo"] == "edicao_nao_permitida"


def test_editar_por_outro_403(cenario, criar_rascunho):
    mid = criar_rascunho()
    assert (
        cenario.outro_aluno.client.patch(f"/api/monografias/{mid}/", {"titulo": "X"}, format="json").status_code == 403
    )
    assert (
        cenario.orientador.client.patch(f"/api/monografias/{mid}/", {"titulo": "X"}, format="json").status_code == 403
    )


def test_idor_aluno_nao_ve_monografia_de_outro(cenario, criar_rascunho):
    mid = criar_rascunho()
    assert cenario.outro_aluno.client.get(f"/api/monografias/{mid}/").status_code == 403
    assert cenario.outro_aluno.client.get("/api/monografias/").data["count"] == 0
    assert cenario.outro_prof.client.get(f"/api/monografias/{mid}/").status_code == 403


def test_listagem_por_papel_e_busca(cenario, criar_rascunho):
    criar_rascunho()
    criar_rascunho(titulo="Aprendizado de máquina", resumo="Redes neurais", palavras_chave=["ia", "ml", "redes"])
    assert cenario.aluno.client.get("/api/monografias/").data["count"] == 2
    assert cenario.orientador.client.get("/api/monografias/").data["count"] == 2
    assert cenario.coord.client.get("/api/monografias/").data["count"] == 2
    assert cenario.outro_prof.client.get("/api/monografias/").data["count"] == 0
    r = cenario.aluno.client.get("/api/monografias?busca=sistemas+distribuidos")
    assert r.status_code == 200 and r.data["count"] == 1
    r = cenario.aluno.client.get("/api/monografias/?palavras_chave=ia,outra")
    assert r.data["count"] == 1
    r = cenario.aluno.client.get(f"/api/monografias/?orientador={cenario.orientador_ref.id}&status=rascunho")
    assert r.data["count"] == 2


def test_excluir(cenario, criar_rascunho, submetida):
    mid = criar_rascunho()
    assert cenario.aluno.client.delete(f"/api/monografias/{submetida}/").status_code == 403  # não é rascunho
    assert cenario.aluno.client.delete(f"/api/monografias/{mid}/").status_code == 204
    assert cenario.coord.client.delete(f"/api/monografias/{submetida}/").status_code == 204
    assert eventos_outbox("monografia.excluida")


def test_excluir_publicada_409(cenario, publicada):
    for c in (cenario.admin.client, cenario.coord.client, cenario.aluno.client):
        r = c.delete(f"/api/monografias/{publicada}/")
        assert r.status_code == 409 and r.data["codigo"] == "monografia_publicada_imutavel"


# --- submissão e máquina de estados --------------------------------------------------


def test_submeter_incompleta_400(cenario, criar_rascunho):
    mid = criar_rascunho(palavras_chave=["só uma"])
    r = cenario.aluno.client.post(f"/api/monografias/{mid}/submeter/")
    assert r.status_code == 400 and r.data["codigo"] == "submissao_incompleta"
    assert "arquivo" in r.data["detalhes"]["faltando"]
    assert not get_redis().exists(f"upload_em_andamento:{mid}")


def test_submeter_202_evento_e_lock(cenario, criar_rascunho):
    from apps.monografias.models import Monografia

    mid = criar_rascunho()
    cenario.aluno.client.post(f"/api/monografias/{mid}/arquivo/", {"arquivo": arquivo_pdf()}, format="multipart")
    r = cenario.aluno.client.post(f"/api/monografias/{mid}/submeter/")
    assert r.status_code == 202 and r.data["status"] == "em_avaliacao"
    m = Monografia.objects.get(pk=mid)
    assert m.submetida_em is not None
    ev = eventos_outbox("monografia.submetida")[-1]
    assert ev["data"]["id"] == mid and ev["data"]["sha256"] == m.arquivo_sha256
    assert get_redis().exists(f"upload_em_andamento:{mid}")  # mantido até a extração
    # reenvio durante o processamento
    r2 = cenario.aluno.client.post(f"/api/monografias/{mid}/submeter/")
    assert r2.status_code == 409 and r2.data["codigo"] == "upload_em_andamento"


def test_texto_extraido_libera_lock(cenario, criar_rascunho):
    from apps.monografias.eventos import HANDLERS
    from apps.monografias.models import Monografia
    from tcc_common.events.consumer import encontrar_handler, processar_evento

    mid = criar_rascunho()
    cenario.aluno.client.post(f"/api/monografias/{mid}/arquivo/", {"arquivo": arquivo_pdf()}, format="multipart")
    cenario.aluno.client.post(f"/api/monografias/{mid}/submeter/")
    env = envelope("monografia.texto_extraido", {"id": mid, "paginas": 3, "sem_texto": False})
    processar_evento(env, encontrar_handler(HANDLERS, env["type"]))
    assert not get_redis().exists(f"upload_em_andamento:{mid}")
    assert Monografia.objects.get(pk=mid).texto_extraido is True


def test_status_nao_muda_por_atribuicao_direta(cenario, criar_rascunho):
    from apps.monografias.estados import TransicaoInvalida
    from apps.monografias.models import Monografia

    m = Monografia.objects.get(pk=criar_rascunho())
    m.status = "publicada"
    with pytest.raises(TransicaoInvalida):
        m.save()


def test_transicao_invalida_409(cenario, criar_rascunho):
    from apps.monografias.estados import TransicaoInvalida, validar_transicao
    from apps.monografias.models import Monografia

    with pytest.raises(TransicaoInvalida):
        validar_transicao("rascunho", "publicada")
    with pytest.raises(TransicaoInvalida):
        validar_transicao("publicada", "rascunho")
    with pytest.raises(TransicaoInvalida):
        validar_transicao("reprovada", "aprovada")
    m = Monografia.objects.get(pk=criar_rascunho())
    with pytest.raises(TransicaoInvalida):
        m.registrar_resultado_banca("aprovada", False)
    r = cenario.orientador.client.post(f"/api/monografias/{m.id}/aprovar-orientador/")
    assert r.status_code == 409 and r.data["codigo"] == "transicao_invalida"


# --- aprovação do orientador ------------------------------------------------------------


def test_aprovacao_por_nao_orientador_403(cenario, submetida):
    assert cenario.outro_prof.client.post(f"/api/monografias/{submetida}/aprovar-orientador/").status_code == 403
    assert cenario.aluno.client.post(f"/api/monografias/{submetida}/aprovar-orientador/").status_code == 403
    assert cenario.coord.client.post(f"/api/monografias/{submetida}/aprovar-orientador/").status_code == 403


def test_aprovacao_grava_snapshot_e_evento(cenario, aprovada_orientador):
    from apps.monografias.models import Monografia

    m = Monografia.objects.get(pk=aprovada_orientador)
    assert m.aprovacao_orientador == "aprovada" and m.arquivo_sha256_aprovado == m.arquivo_sha256
    assert eventos_outbox("monografia.aprovada_orientador")[-1]["data"]["sha256_aprovado"] == m.arquivo_sha256
    r = cenario.orientador.client.post(f"/api/monografias/{m.id}/aprovar-orientador/")
    assert r.status_code == 409


def test_rejeicao_volta_a_rascunho(cenario, submetida):
    r = cenario.orientador.client.post(
        f"/api/monografias/{submetida}/rejeitar-orientador/",
        {"motivo": "Faltam referências bibliográficas."},
        format="json",
    )
    assert r.status_code == 200
    assert r.data["status"] == "rascunho" and r.data["aprovacao_orientador"] == "rejeitada"
    assert eventos_outbox("monografia.rejeitada_orientador")[-1]["data"]["motivo"].startswith("Faltam")
    # aluno corrige e reenvia
    assert (
        cenario.aluno.client.post(
            f"/api/monografias/{submetida}/arquivo/", {"arquivo": arquivo_pdf()}, format="multipart"
        ).status_code
        == 201
    )


# --- resultado da banca e publicação ------------------------------------------------------


def _resultado(mid, resultado="aprovada", exige_correcao=False):
    from apps.monografias.eventos import HANDLERS
    from tcc_common.events.consumer import encontrar_handler, processar_evento

    env = envelope(
        "banca.resultado_calculado",
        {
            "banca_id": str(uuid.uuid4()),
            "monografia_id": mid,
            "aluno_id": None,
            "orientador_id": None,
            "resultado": resultado,
            "media": "8.0",
            "exige_correcao": exige_correcao,
            "data_defesa": "2026-06-10T14:00:00Z",
        },
    )
    return processar_evento(env, encontrar_handler(HANDLERS, env["type"])), env


def _enviar_termo(cenario, mid):
    r = cenario.aluno.client.post(
        f"/api/monografias/{mid}/documentos/",
        {"tipo": "termo_autorizacao_publicacao", "arquivo": arquivo_pdf(nome="termo.pdf")},
        format="multipart",
    )
    assert r.status_code == 201, r.data
    return r.data["id"]


@pytest.fixture
def publicada(cenario, aprovada_orientador):
    _resultado(aprovada_orientador)
    doc = _enviar_termo(cenario, aprovada_orientador)
    r = cenario.coord.client.post(f"/api/monografias/{aprovada_orientador}/documentos/{doc}/validar-assinatura/")
    assert r.status_code == 200
    return aprovada_orientador


def test_resultado_banca_consumer_idempotente(cenario, aprovada_orientador):
    from apps.monografias.models import Monografia

    res, env = _resultado(aprovada_orientador, "aprovada", exige_correcao=True)
    assert res == "processado"
    m = Monografia.objects.get(pk=aprovada_orientador)
    assert m.status == "aprovada" and m.exige_correcao and m.defendida_em.year == 2026
    from apps.monografias.eventos import HANDLERS
    from tcc_common.events.consumer import encontrar_handler, processar_evento

    assert processar_evento(env, encontrar_handler(HANDLERS, env["type"])) == "duplicado"


def test_resultado_reprovada_terminal(cenario, aprovada_orientador):
    from apps.monografias.models import Monografia

    _resultado(aprovada_orientador, "reprovada")
    assert Monografia.objects.get(pk=aprovada_orientador).status == "reprovada"


def test_publicacao_automatica_completa(cenario, publicada):
    from apps.monografias.models import Monografia

    m = Monografia.objects.get(pk=publicada)
    assert m.status == "publicada" and m.publicada_em
    ev = eventos_outbox("monografia.publicada")[-1]["data"]
    assert ev["autor_nome"] == "Ana Aluna" and ev["orientador_nome"] == "Prof. Orientador"
    assert ev["curso_nome"] == "Sistemas de Informação" and ev["ano_defesa"] == 2026
    assert ev["palavras_chave"] == ["sistemas distribuídos", "redis", "rabbitmq"]


def test_termo_so_validado_por_coordenador(cenario, aprovada_orientador):
    _resultado(aprovada_orientador)
    doc = _enviar_termo(cenario, aprovada_orientador)
    url = f"/api/monografias/{aprovada_orientador}/documentos/{doc}/validar-assinatura/"
    assert cenario.aluno.client.post(url).status_code == 403
    assert cenario.orientador.client.post(url).status_code == 403


@pytest.mark.parametrize(
    "faltando", ["status", "termo", "termo_nao_validado", "correcao", "correcao_nao_validada", "integridade"]
)
def test_tentar_publicar_com_precondicao_faltando(cenario, aprovada_orientador, faltando):
    from apps.monografias.models import DocumentoComplementar, Monografia

    if faltando != "status":
        _resultado(aprovada_orientador, exige_correcao=faltando.startswith("correcao"))
    m = Monografia.objects.get(pk=aprovada_orientador)
    if faltando not in ("termo",):
        DocumentoComplementar.objects.create(
            monografia=m,
            tipo="termo_autorizacao_publicacao",
            sha256="x",
            assinado_validado=faltando != "termo_nao_validado",
            arquivo="t.pdf",
        )
    if faltando == "correcao_nao_validada":
        DocumentoComplementar.objects.create(monografia=m, tipo="versao_corrigida", sha256="y", arquivo="v.pdf")
    if faltando == "integridade":
        Monografia.objects.filter(pk=m.pk).update(integridade_ok=False)
    m = Monografia.objects.get(pk=m.pk)
    assert m.tentar_publicar() is False
    assert Monografia.objects.get(pk=m.pk).status != "publicada"
    assert m.pendencias_publicacao()


def test_fluxo_com_ressalvas_versao_corrigida(cenario, aprovada_orientador):
    from apps.monografias.models import Monografia

    mid = aprovada_orientador
    _resultado(mid, exige_correcao=True)
    doc = _enviar_termo(cenario, mid)
    cenario.coord.client.post(f"/api/monografias/{mid}/documentos/{doc}/validar-assinatura/")
    assert Monografia.objects.get(pk=mid).status == "aprovada"  # falta a correção
    r = cenario.aluno.client.post(
        f"/api/monografias/{mid}/documentos/",
        {"tipo": "versao_corrigida", "arquivo": arquivo_pdf(nome="corrigida.pdf")},
        format="multipart",
    )
    assert r.status_code == 201
    assert Monografia.objects.get(pk=mid).status == "aprovada"  # falta o orientador validar
    assert cenario.aluno.client.post(f"/api/monografias/{mid}/validar-correcao/").status_code == 403
    r = cenario.orientador.client.post(f"/api/monografias/{mid}/validar-correcao/")
    assert r.status_code == 200
    m = Monografia.objects.get(pk=mid)
    assert m.status == "publicada" and m.arquivo_sha256 == m.arquivo_sha256_aprovado == r.data["arquivo_sha256"]


def test_versao_corrigida_sem_ressalvas_409(cenario, aprovada_orientador):
    _resultado(aprovada_orientador, exige_correcao=False)
    r = cenario.aluno.client.post(
        f"/api/monografias/{aprovada_orientador}/documentos/",
        {"tipo": "versao_corrigida", "arquivo": arquivo_pdf()},
        format="multipart",
    )
    assert r.status_code == 409


def test_documento_pdf_invalido_415(cenario, aprovada_orientador):
    from django.core.files.uploadedfile import SimpleUploadedFile

    r = cenario.aluno.client.post(
        f"/api/monografias/{aprovada_orientador}/documentos/",
        {"tipo": "termo_autorizacao_publicacao", "arquivo": SimpleUploadedFile("t.pdf", b"nao pdf", "application/pdf")},
        format="multipart",
    )
    assert r.status_code == 415


# --- integridade -----------------------------------------------------------------------


def test_integridade_ok(cenario, aprovada_orientador):
    r = cenario.orientador.client.post(f"/api/monografias/{aprovada_orientador}/verificar-integridade/")
    assert r.status_code == 200 and r.data["integridade_ok"] is True


def test_integridade_violada(cenario, aprovada_orientador):
    from apps.monografias.models import Monografia

    m = Monografia.objects.get(pk=aprovada_orientador)
    with default_storage.open(m.arquivo.name, "ab") as f:  # alteração não autorizada em disco
        f.write(b"adulterado")
    r = cenario.coord.client.post(f"/api/monografias/{m.id}/verificar-integridade/")
    assert r.status_code == 200 and r.data["integridade_ok"] is False
    assert Monografia.objects.get(pk=m.id).integridade_ok is False
    ev = eventos_outbox("monografia.integridade_violada")[-1]["data"]
    assert ev["sha_esperado"] == m.arquivo_sha256_aprovado and ev["sha_atual"] != ev["sha_esperado"]
    audit = [e for e in eventos_outbox("audit.registro") if e["data"]["acao"] == "integridade_violada"]
    assert audit and audit[-1]["data"]["nivel"] == "critico"
    # e bloqueia a publicação
    _resultado(m.id)
    doc = _enviar_termo(cenario, m.id)
    cenario.coord.client.post(f"/api/monografias/{m.id}/documentos/{doc}/validar-assinatura/")
    assert Monografia.objects.get(pk=m.id).status == "aprovada"


def test_comando_verificar_integridade_todas(cenario, aprovada_orientador, capsys):
    from django.core.management import call_command

    call_command("verificar_integridade_todas")
    assert "1 verificadas, 0 com divergência" in capsys.readouterr().out


# --- endpoint interno ------------------------------------------------------------------


def test_endpoint_interno_exige_token_de_servico(api, servico_client, submetida):
    assert api.get(f"/internal/monografias/{submetida}/arquivo/").status_code == 403
    r = servico_client.get(f"/internal/monografias/{submetida}/arquivo/")
    assert r.status_code == 200 and b"".join(r.streaming_content).startswith(b"%PDF-")
    assert servico_client.get(f"/internal/monografias/{submetida}/").data["status"] == "em_avaliacao"


def test_consumer_cadastro_mantem_read_models():
    from apps.monografias.eventos import HANDLERS
    from apps.monografias.models import ProfessorRef
    from tcc_common.events.consumer import encontrar_handler, processar_evento

    pid = str(uuid.uuid4())
    env = envelope("cadastro.professor.upserted", {"id": pid, "nome": "P", "email": "p@x.br", "departamento": "D"})
    processar_evento(env, encontrar_handler(HANDLERS, env["type"]))
    assert ProfessorRef.objects.get(pk=pid).nome == "P"
    env = envelope("cadastro.professor.deleted", {"id": pid})
    processar_evento(env, encontrar_handler(HANDLERS, env["type"]))
    assert not ProfessorRef.objects.filter(pk=pid).exists()

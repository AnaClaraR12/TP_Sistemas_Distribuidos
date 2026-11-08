"""Evento -> e-mails certos aos destinatários certos; idempotência; retry em falha SMTP."""

import uuid

import pytest
from django.core import mail

from tcc_common.testing import envelope

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _rapido(settings):
    settings.NOTIFICACAO_BACKOFF_S = 0
    settings.FRONTEND_URL = "http://localhost:8080"


@pytest.fixture
def refs(db):
    from apps.notificacoes.models import AlunoRef, CursoRef, ProfessorRef

    ori = ProfessorRef.objects.create(id=uuid.uuid4(), nome="Orientador", email="ori@ufvjm.edu.br")
    coord = ProfessorRef.objects.create(id=uuid.uuid4(), nome="Coord", email="coord@ufvjm.edu.br")
    curso = CursoRef.objects.create(id=uuid.uuid4(), nome="SI", coordenador_id=coord.id)
    aluno = AlunoRef.objects.create(id=uuid.uuid4(), nome="Ana", email="ana@ufvjm.edu.br", curso_id=curso.id)
    return {"ori": ori, "coord": coord, "curso": curso, "aluno": aluno}


def _base(refs, **kw):
    return {
        "id": str(uuid.uuid4()),
        "titulo": "Meu TCC",
        "status": "em_avaliacao",
        "aprovacao_orientador": "pendente",
        "aluno_id": str(refs["aluno"].id),
        "orientador_id": str(refs["ori"].id),
        "curso_id": str(refs["curso"].id),
        **kw,
    }


def _processar(env):
    from apps.notificacoes.eventos import HANDLERS
    from tcc_common.events.consumer import encontrar_handler, processar_evento

    return processar_evento(env, encontrar_handler(HANDLERS, env["type"]))


def _para():
    return sorted(m.to[0] for m in mail.outbox)


def test_submissao_notifica_orientador(refs):
    _processar(envelope("monografia.submetida", {**_base(refs), "sha256": "x", "submetida_em": "2026-01-01T00:00:00Z"}))
    assert _para() == ["ori@ufvjm.edu.br"]
    assert mail.outbox[0].subject == "Nova submissão aguardando sua aprovação"


def test_texto_extraido_notifica_orientador_e_aluno(refs):
    _processar(
        envelope(
            "monografia.texto_extraido",
            {
                "id": str(uuid.uuid4()),
                "paginas": 10,
                "sem_texto": False,
                "orientador_id": str(refs["ori"].id),
                "aluno_id": str(refs["aluno"].id),
            },
        )
    )
    assert _para() == ["ana@ufvjm.edu.br", "ori@ufvjm.edu.br"]


def test_aprovacao_notifica_aluno_e_coordenador(refs):
    _processar(envelope("monografia.aprovada_orientador", {**_base(refs), "sha256_aprovado": "x"}))
    assert _para() == ["ana@ufvjm.edu.br", "coord@ufvjm.edu.br"]


def test_rejeicao_envia_motivo_ao_aluno(refs):
    _processar(envelope("monografia.rejeitada_orientador", {**_base(refs), "motivo": "Faltam referências."}))
    assert _para() == ["ana@ufvjm.edu.br"] and "Faltam referências." in mail.outbox[0].body


def test_banca_agendada_notifica_todos_os_membros_e_aluno(refs):
    membros = [
        {"nome": "Orientador", "email": "ori@ufvjm.edu.br", "tipo": "interno", "funcao": "orientador"},
        {"nome": "P1", "email": "p1@ufvjm.edu.br", "tipo": "interno", "funcao": "membro"},
        {"nome": "Externa", "email": "ext@outra.edu.br", "tipo": "externo", "funcao": "membro"},
    ]
    _processar(
        envelope(
            "banca.agendada",
            {
                "banca_id": "b",
                "monografia_id": "m",
                "titulo": "Meu TCC",
                "aluno_id": str(refs["aluno"].id),
                "data_hora": "2026-06-10T14:00:00Z",
                "local": "Sala 1",
                "link": None,
                "membros": membros,
            },
        )
    )
    assert _para() == ["ana@ufvjm.edu.br", "ext@outra.edu.br", "ori@ufvjm.edu.br", "p1@ufvjm.edu.br"]
    assert "Sala 1" in mail.outbox[0].body and "Externa (membro)" in mail.outbox[0].body


def test_convite_externo_tem_link_com_token_mas_banco_nao(refs):
    from apps.notificacoes.models import Notificacao

    _processar(
        envelope(
            "banca.convite_enviado",
            {
                "banca_id": "b1",
                "monografia_id": "m",
                "titulo": "T",
                "data_hora": "2026-06-10T14:00:00Z",
                "local": None,
                "link": "https://meet/x",
                "membro": {"nome": "Ext", "email": "ext@outra.edu.br", "tipo": "externo"},
                "token": "TOKEN-SECRETO-123",
                "expira_em": "2026-06-17T14:00:00Z",
            },
        )
    )
    assert "http://localhost:8080/banca/externo/TOKEN-SECRETO-123" in mail.outbox[0].body
    n = Notificacao.objects.get()
    assert "TOKEN-SECRETO-123" not in n.corpo and "***" in n.corpo


def test_resultado_notifica_aluno_orientador_coordenador(refs):
    _processar(
        envelope(
            "banca.resultado_calculado",
            {
                "banca_id": "b",
                "monografia_id": "m",
                "aluno_id": str(refs["aluno"].id),
                "orientador_id": str(refs["ori"].id),
                "curso_id": str(refs["curso"].id),
                "titulo": "T",
                "resultado": "aprovada",
                "media": "8.5",
                "exige_correcao": True,
                "data_defesa": "2026-06-10T14:00:00Z",
            },
        )
    )
    assert _para() == ["ana@ufvjm.edu.br", "coord@ufvjm.edu.br", "ori@ufvjm.edu.br"]
    assert "versão corrigida" in mail.outbox[0].body


def test_publicacao_notifica_aluno_com_link_publico(refs):
    base = _base(refs, status="publicada")
    _processar(
        envelope(
            "monografia.publicada",
            {
                **base,
                "resumo": "",
                "palavras_chave": [],
                "autor_nome": "Ana",
                "orientador_nome": "O",
                "curso_nome": "SI",
                "ano_defesa": 2026,
                "sha256": "x",
                "publicada_em": "2026-07-01T00:00:00Z",
            },
        )
    )
    assert _para() == ["ana@ufvjm.edu.br"]
    assert f"http://localhost:8080/repositorio/{base['id']}" in mail.outbox[0].body


def test_integridade_alerta_admin_e_coordenador(refs, settings):
    settings.NOTIFICACOES_ADMIN_EMAILS = ["admin@tcc.local"]
    _processar(envelope("monografia.integridade_violada", {**_base(refs), "sha_esperado": "a", "sha_atual": "b"}))
    assert _para() == ["admin@tcc.local", "coord@ufvjm.edu.br"]


def test_evento_repetido_nao_duplica_email(refs):
    env = envelope("monografia.rejeitada_orientador", {**_base(refs), "motivo": "x" * 12})
    _processar(env)
    _processar(env)
    from apps.notificacoes.eventos import on_rejeitada_orientador

    on_rejeitada_orientador(env)  # mesmo sem a tabela evento_processado, unique(evento, email, tipo) protege
    assert len(mail.outbox) == 1


def test_falha_smtp_faz_retry(refs, monkeypatch, settings):
    from apps.notificacoes import envio
    from apps.notificacoes.models import Notificacao

    settings.NOTIFICACAO_TENTATIVAS = 3
    chamadas = {"n": 0}
    original = envio.send_mail

    def instavel(*a, **kw):
        chamadas["n"] += 1
        if chamadas["n"] < 3:
            raise ConnectionRefusedError("smtp fora")
        return original(*a, **kw)

    monkeypatch.setattr(envio, "send_mail", instavel)
    _processar(envelope("monografia.rejeitada_orientador", {**_base(refs), "motivo": "y" * 12}))
    n = Notificacao.objects.get()
    assert n.status == "enviada" and n.tentativas == 3 and len(mail.outbox) == 1


def test_falha_smtp_persistente_marca_falhou_e_reenvia_depois(refs, monkeypatch, settings):
    from django.core.management import call_command

    from apps.notificacoes import envio
    from apps.notificacoes.models import Notificacao

    monkeypatch.setattr(envio, "send_mail", lambda *a, **k: (_ for _ in ()).throw(ConnectionRefusedError("fora")))
    _processar(envelope("monografia.rejeitada_orientador", {**_base(refs), "motivo": "z" * 12}))
    assert Notificacao.objects.get().status == "falhou"
    monkeypatch.undo()
    call_command("reenviar_notificacoes")
    assert Notificacao.objects.get().status == "enviada"


def test_minhas_notificacoes_e_marcar_lida(refs, ator):
    _processar(envelope("monografia.rejeitada_orientador", {**_base(refs), "motivo": "w" * 12}))
    aluno = ator("aluno", email="ana@ufvjm.edu.br")
    r = aluno.client.get("/api/notificacoes/minhas/")
    assert r.status_code == 200 and r.data["count"] == 1
    nid = r.data["results"][0]["id"]
    assert ator("aluno", email="outro@x.br").client.post(f"/api/notificacoes/{nid}/lida/").status_code == 404
    assert aluno.client.post(f"/api/notificacoes/{nid}/lida/").data["lida_em"]
    assert aluno.client.get("/api/notificacoes/minhas/?nao_lidas=1").data["count"] == 0


def test_anonimo_401(api):
    assert api.get("/api/notificacoes/minhas/").status_code == 401

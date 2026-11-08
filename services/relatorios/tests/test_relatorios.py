"""Métricas do dashboard com dados controlados, escopo por papel, cache e consumers."""

import uuid
from datetime import UTC, datetime

import pytest

from tcc_common.testing import envelope

pytestmark = pytest.mark.django_db

C1, C2 = uuid.uuid4(), uuid.uuid4()
P1, P2 = uuid.uuid4(), uuid.uuid4()


def fato(**kw):
    from apps.relatorios.models import FatoMonografia

    base = {
        "monografia_id": uuid.uuid4(),
        "curso_id": C1,
        "curso_nome": "SI",
        "orientador_id": P1,
        "orientador_nome": "Prof A",
        "aluno_id": uuid.uuid4(),
        "status": "em_avaliacao",
    }
    return FatoMonografia.objects.create(**{**base, **kw})


def dt(ano, mes, dia):
    return datetime(ano, mes, dia, 12, tzinfo=UTC)


@pytest.fixture
def dados():
    # SI / Prof A: 2 aprovadas (2025, 2026), 1 reprovada (2026), 1 em avaliação
    fato(
        status="publicada",
        resultado="aprovada",
        submetida_em=dt(2025, 3, 1),
        defendida_em=dt(2025, 3, 31),
        ano_defesa=2025,
    )
    fato(
        status="aprovada",
        resultado="aprovada",
        submetida_em=dt(2026, 1, 1),
        defendida_em=dt(2026, 1, 11),
        ano_defesa=2026,
    )
    fato(
        status="reprovada",
        resultado="reprovada",
        submetida_em=dt(2026, 2, 1),
        defendida_em=dt(2026, 2, 21),
        ano_defesa=2026,
    )
    fato()
    # ENG / Prof B: 1 aprovada
    fato(
        curso_id=C2,
        curso_nome="ENG",
        orientador_id=P2,
        orientador_nome="Prof B",
        status="aprovada",
        resultado="aprovada",
        submetida_em=dt(2026, 4, 1),
        defendida_em=dt(2026, 4, 5),
        ano_defesa=2026,
    )


def test_por_curso(ator, dados):
    r = ator("admin").client.get("/api/relatorios/monografias-por-curso/")
    linhas = {x["curso_nome"]: x for x in r.data["dados"]}
    assert linhas["SI"]["total"] == 4 and linhas["SI"]["aprovadas"] == 2 and linhas["SI"]["reprovadas"] == 1
    assert linhas["SI"]["publicadas"] == 1 and linhas["ENG"]["total"] == 1


def test_por_orientador(ator, dados):
    r = ator("admin").client.get("/api/relatorios/monografias-por-orientador/")
    assert {x["orientador_nome"]: x["total"] for x in r.data["dados"]} == {"Prof A": 4, "Prof B": 1}


def test_por_ano(ator, dados):
    r = ator("admin").client.get("/api/relatorios/monografias-por-ano-defesa/")
    assert [(x["ano"], x["total"]) for x in r.data["dados"]] == [(2025, 1), (2026, 3)]


def test_taxa_aprovacao(ator, dados):
    d = ator("admin").client.get("/api/relatorios/taxa-aprovacao/").data["dados"]
    assert d["geral"] == {"aprovadas": 3, "reprovadas": 1, "taxa": 0.75}
    por_curso = {x["curso_nome"]: x["taxa"] for x in d["por_curso"]}
    assert por_curso == {"ENG": 1.0, "SI": 0.6667}
    assert {x["ano"]: x["taxa"] for x in d["por_ano"]} == {2025: 1.0, 2026: 0.6667}


def test_taxa_divisao_por_zero(ator):
    fato()  # nenhuma defesa
    d = ator("admin").client.get("/api/relatorios/taxa-aprovacao/").data["dados"]
    assert d["geral"]["taxa"] is None and d["por_curso"][0]["taxa"] is None


def test_tempo_medio_submissao_defesa(ator, dados):
    d = ator("admin").client.get("/api/relatorios/tempo-medio-submissao-defesa/").data["dados"]
    # (30 + 10 + 20 + 4) / 4 = 16 dias
    assert d["geral_dias"] == 16.0 and d["amostra"] == 4
    assert {x["curso_nome"]: x["media_dias"] for x in d["por_curso"]} == {"ENG": 4.0, "SI": 20.0}


def test_resumo(ator, dados):
    d = ator("admin").client.get("/api/relatorios/resumo/").data["dados"]
    assert d["total"] == 5 and d["por_status"]["aprovada"] == 2
    assert set(d) >= {"por_curso", "por_orientador", "por_ano", "taxa_aprovacao", "tempo_medio_submissao_defesa"}


def test_escopo_por_papel(ator, dados):
    assert ator("coordenador", curso_ids=[C2]).client.get("/api/relatorios/resumo/").data["dados"]["total"] == 1
    assert ator("professor", professor_id=str(P1)).client.get("/api/relatorios/resumo/").data["dados"]["total"] == 4
    assert ator("aluno").client.get("/api/relatorios/resumo/").data["dados"]["total"] == 0


def test_anonimo_401_e_relatorio_inexistente_404(api, ator):
    assert api.get("/api/relatorios/resumo/").status_code == 401
    assert ator("admin").client.get("/api/relatorios/nao-existe/").status_code == 404


def test_cache_e_invalidacao_por_evento(ator, dados):
    from apps.relatorios.eventos import HANDLERS
    from tcc_common.events.consumer import encontrar_handler, processar_evento

    c = ator("admin").client
    assert c.get("/api/relatorios/resumo/")["X-Cache"] == "MISS"
    assert c.get("/api/relatorios/resumo/")["X-Cache"] == "HIT"
    mid = str(uuid.uuid4())
    env = envelope(
        "monografia.submetida",
        {
            "id": mid,
            "titulo": "Nova",
            "status": "em_avaliacao",
            "aprovacao_orientador": "pendente",
            "aluno_id": None,
            "orientador_id": str(P1),
            "curso_id": str(C1),
            "sha256": "x",
            "submetida_em": "2026-05-01T00:00:00Z",
        },
    )
    processar_evento(env, encontrar_handler(HANDLERS, env["type"]))
    r = c.get("/api/relatorios/resumo/")
    assert r["X-Cache"] == "MISS" and r.data["dados"]["total"] == 6


def test_consumers_fluxo_completo(ator):
    from apps.relatorios.eventos import HANDLERS
    from apps.relatorios.models import FatoMonografia
    from tcc_common.events.consumer import encontrar_handler, processar_evento

    def proc(tipo, data):
        env = envelope(tipo, data)
        return processar_evento(env, encontrar_handler(HANDLERS, tipo))

    cid, pid, mid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    proc("cadastro.curso.upserted", {"id": cid, "nome": "Direito", "codigo": "DIR", "coordenador_id": None})
    proc("cadastro.professor.upserted", {"id": pid, "nome": "Profa X", "email": "x@x", "departamento": "D"})
    base = {
        "id": mid,
        "titulo": "T",
        "status": "em_avaliacao",
        "aprovacao_orientador": "pendente",
        "aluno_id": None,
        "orientador_id": pid,
        "curso_id": cid,
    }
    proc("monografia.submetida", {**base, "sha256": "x", "submetida_em": "2026-03-01T12:00:00Z"})
    proc(
        "banca.resultado_calculado",
        {
            "banca_id": "b",
            "monografia_id": mid,
            "aluno_id": None,
            "orientador_id": pid,
            "resultado": "aprovada",
            "media": "8",
            "exige_correcao": False,
            "data_defesa": "2026-03-11T12:00:00Z",
        },
    )
    f = FatoMonografia.objects.get(pk=mid)
    assert (
        f.curso_nome == "Direito"
        and f.orientador_nome == "Profa X"
        and f.resultado == "aprovada"
        and f.ano_defesa == 2026
    )
    d = ator("admin").client.get("/api/relatorios/tempo-medio-submissao-defesa/").data["dados"]
    assert d["geral_dias"] == 10.0
    proc("monografia.excluida", {"id": mid})
    assert not FatoMonografia.objects.filter(pk=mid).exists()

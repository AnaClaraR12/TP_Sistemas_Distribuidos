import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from tcc_common.testing import eventos_outbox

PARECER = "Trabalho bem estruturado, com revisão bibliográfica adequada e resultados consistentes."


@pytest.fixture
def cenario(db, ator):
    from apps.bancas.models import MonografiaRef, ProfessorRef

    curso_id = uuid.uuid4()
    profs = [
        ProfessorRef.objects.create(id=uuid.uuid4(), nome=f"Prof {i}", email=f"p{i}@ufvjm.edu.br") for i in range(4)
    ]
    aluno_id = uuid.uuid4()
    mono = MonografiaRef.objects.create(
        id=uuid.uuid4(),
        titulo="TCC",
        status="em_avaliacao",
        aprovacao_orientador="aprovada",
        aluno_id=aluno_id,
        orientador_id=profs[0].id,
        curso_id=curso_id,
    )

    class C:
        pass

    c = C()
    c.mono, c.profs, c.curso_id = mono, profs, curso_id
    c.orientador = ator("professor", professor_id=str(profs[0].id))
    c.p1 = ator("professor", professor_id=str(profs[1].id))
    c.p2 = ator("professor", professor_id=str(profs[2].id))
    c.p3 = ator("professor", professor_id=str(profs[3].id))
    c.coord = ator("coordenador", professor_id=str(uuid.uuid4()), curso_ids=[curso_id])
    c.aluno = ator("aluno", aluno_id=str(aluno_id))
    c.admin = ator("admin")
    return c


def payload_banca(c, inicio=None, externo=True, membros=None, **kw):
    inicio = inicio or (timezone.now() + timedelta(days=10)).replace(microsecond=0)
    if membros is None:
        membros = [{"tipo": "interno", "professor_id": str(c.profs[1].id)}]
        if externo:
            membros.append(
                {"tipo": "externo", "nome": "Dra. Externa", "email": "externa@outra.edu.br", "instituicao": "UFMG"}
            )
        else:
            membros.append({"tipo": "interno", "professor_id": str(c.profs[2].id)})
    return {
        "monografia_id": str(kw.get("monografia_id", c.mono.id)),
        "data_hora_inicio": inicio.isoformat(),
        "local": kw.get("local", "Sala 101"),
        "link": kw.get("link"),
        "membros": membros,
    }


def token_externo(email="externa@outra.edu.br") -> str:
    ev = [e for e in eventos_outbox("banca.convite_enviado") if e["data"]["membro"]["email"] == email][-1]
    return ev["data"]["token"]


@pytest.fixture
def criar_banca(cenario):
    def _criar(cliente=None, **kw):
        r = (cliente or cenario.coord.client).post("/api/bancas", payload_banca(cenario, **kw), format="json")
        assert r.status_code == 201, r.data
        return r.data

    return _criar


def confirmar_todos(cenario, banca, api):
    from apps.bancas.models import MembroBanca

    for m in banca["membros"]:
        if m["tipo"] == "externo":
            r = api.post(
                "/api/bancas/externo/confirmar/",
                {"resposta": "confirmado"},
                format="json",
                HTTP_X_BANCA_TOKEN=token_externo(m["email"]),
            )
        else:
            ator = next(
                a
                for a in (cenario.orientador, cenario.p1, cenario.p2, cenario.p3)
                if a.professor_id == m["professor_id"]
            )
            r = ator.client.post(
                f"/api/bancas/{banca['id']}/membros/{m['id']}/confirmar/", {"resposta": "confirmado"}, format="json"
            )
        assert r.status_code == 200, r.data
    assert not MembroBanca.objects.filter(banca_id=banca["id"]).exclude(confirmacao="confirmado").exists()


@pytest.fixture
def banca_realizada(cenario, criar_banca, api):
    b = criar_banca()
    confirmar_todos(cenario, b, api)
    assert cenario.coord.client.post(f"/api/bancas/{b['id']}/agendar/").status_code == 200
    assert cenario.coord.client.post(f"/api/bancas/{b['id']}/marcar-realizada/").status_code == 200
    return b

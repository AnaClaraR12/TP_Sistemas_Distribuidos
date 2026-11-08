"""Teste ponta a ponta contra o GATEWAY (sistema de pé + `make seed`).

    make up && make seed && make e2e

Fluxo feliz completo (Fase 12) + fluxos negativos. Usa os usuários de demonstração.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from tcc_cliente import MailHog, Sessao, aguardar, pdf_simples  # noqa: E402

GW = os.environ.get("GATEWAY_URL", "http://localhost:8080")
MAILHOG = os.environ.get("MAILHOG_URL", "http://localhost:8025")
SENHA = os.environ.get("SEED_SENHA_PADRAO", "Demo@Tcc#2026")
D = "demo.tcc.br"
PARECER = "Excelente trabalho, metodologia rigorosa, resultados relevantes e texto muito bem escrito."


def _sistema_no_ar() -> bool:
    try:
        return requests.get(f"{GW}/gateway/health", timeout=3).status_code == 200
    except requests.RequestException:
        return False


pytestmark = pytest.mark.skipif(not _sistema_no_ar(), reason=f"gateway {GW} indisponível (rode `make up && make seed`)")


@pytest.fixture(scope="module")
def s():
    class S:
        pass

    x = S()
    x.aluno = Sessao.login(GW, f"aluno20@{D}", SENHA)
    x.orientador_id = x.aluno.perfil["vinculos"]["aluno"]["orientador_atual"]["id"]
    profs = Sessao.login(GW, f"prof1@{D}", SENHA).get("/api/auth/professores/?limit=50").json()["results"]
    x.prof_email = {p["id"]: p["email"] for p in profs}
    x.orientador = Sessao.login(GW, x.prof_email[x.orientador_id], SENHA)
    x.coord = (
        Sessao.login(GW, f"prof1@{D}", SENHA)
        if x.aluno.perfil["vinculos"]["aluno"]["curso"]["nome"].startswith("Sistemas")
        else Sessao.login(GW, f"prof2@{D}", SENHA)
    )
    outro = next(
        pid for pid in x.prof_email if pid != x.orientador_id and x.prof_email[pid] not in (f"prof1@{D}", f"prof2@{D}")
    )
    x.membro_id = outro
    x.membro = Sessao.login(GW, x.prof_email[outro], SENHA)
    x.mail = MailHog(MAILHOG)
    x.termo_unico = "zeugma" + uuid.uuid4().hex[:6]  # palavra que só existe no corpo do PDF
    return x


def test_fluxo_feliz_completo(s):
    # 1. aluno cria rascunho -> upload -> submete
    m = s.aluno.post(
        "/api/monografias",
        json={
            "titulo": f"E2E sistemas distribuidos {uuid.uuid4().hex[:6]}",
            "resumo": "Fluxo completo automatizado.",
            "palavras_chave": ["e2e", "sistemas distribuídos", "teste"],
            "orientador_id": s.orientador_id,
        },
    ).json()
    mid = m["id"]
    s.aluno.upload(mid, pdf_simples(["Teste ponta a ponta", f"termo exclusivo {s.termo_unico}"]))
    t0 = time.perf_counter()
    r = s.aluno.post(f"/api/monografias/{mid}/submeter/", esperado=(202,))
    assert time.perf_counter() - t0 < 1.0 and r.json()["status"] == "em_avaliacao"

    # 2. evento processado: texto extraído (consumer do repositório) e lock liberado
    aguardar(lambda: s.aluno.get(f"/api/monografias/{mid}/").json()["texto_extraido"], 90, 1, "extração de texto")
    aguardar(lambda: s.mail.mensagens(s.orientador.perfil["email"]), 60, 1, "e-mail ao orientador")

    # 3. orientador aprova
    s.orientador.post(f"/api/monografias/{mid}/aprovar-orientador/")

    # 4. coordenador cria banca (2 internos + 1 externo), todos confirmam, agenda
    externo = f"ext-{uuid.uuid4().hex[:6]}@{D}"
    inicio = (datetime.now(UTC) + timedelta(days=30, hours=uuid.uuid4().int % 500)).replace(microsecond=0)
    banca = aguardar(
        lambda: s.coord.post(
            "/api/bancas",
            json={
                "monografia_id": mid,
                "data_hora_inicio": inicio.isoformat(),
                "link": "https://meet.exemplo.br/e2e",
                "membros": [
                    {"tipo": "interno", "professor_id": s.membro_id},
                    {"tipo": "externo", "nome": "Dra. E2E", "email": externo, "instituicao": "USP"},
                ],
            },
            esperado=(201,),
        ).json(),
        60,
        2,
        "read model da monografia aprovada",
    )
    r = s.coord.post(f"/api/bancas/{banca['id']}/agendar/", esperado=(409,))
    assert r.json()["codigo"] == "confirmacoes_pendentes"
    token = aguardar(lambda: s.mail.token_convite(externo), 60, 1, "convite externo no MailHog")
    Sessao(GW).post("/api/bancas/externo/confirmar/", json={"resposta": "confirmado"}, headers={"X-Banca-Token": token})
    for mb in banca["membros"]:
        if mb["tipo"] == "interno":
            sess = s.orientador if mb["professor_id"] == s.orientador_id else s.membro
            sess.post(f"/api/bancas/{banca['id']}/membros/{mb['id']}/confirmar/", json={"resposta": "confirmado"})
    s.coord.post(f"/api/bancas/{banca['id']}/agendar/")

    # 5. e-mails de agendamento para TODOS os membros e o aluno
    for email in [s.aluno.perfil["email"], s.orientador.perfil["email"], s.membro.perfil["email"], externo]:
        aguardar(
            lambda e=email: any(
                "agendada" in m["Content"]["Headers"]["Subject"][0].lower() for m in s.mail.mensagens(e)
            ),
            60,
            1,
            f"e-mail de agendamento para {email}",
        )

    # 6. 3 avaliações -> resultado calculado -> monografia aprovada (e não antes)
    s.coord.post(f"/api/bancas/{banca['id']}/marcar-realizada/")
    s.orientador.post(
        f"/api/bancas/{banca['id']}/avaliacoes/",
        json={"nota": 9, "parecer": PARECER, "recomendacao": "aprovado_sem_ressalvas"},
    )
    s.membro.post(
        f"/api/bancas/{banca['id']}/avaliacoes/",
        json={"nota": 8.5, "parecer": PARECER, "recomendacao": "aprovado_sem_ressalvas"},
    )
    time.sleep(3)
    assert s.coord.get(f"/api/bancas/{banca['id']}/").json()["resultado_final"] is None  # 2 de 3
    Sessao(GW).post(
        "/api/bancas/externo/avaliacao/",
        json={"nota": 9.5, "parecer": PARECER, "recomendacao": "aprovado_sem_ressalvas"},
        headers={"X-Banca-Token": token},
    )
    aguardar(lambda: s.aluno.get(f"/api/monografias/{mid}/").json()["status"] == "aprovada", 60, 1, "status aprovada")

    # 7. termo + validação -> publicada automaticamente
    doc = s.aluno.documento(mid, "termo_autorizacao_publicacao", pdf_simples(["Termo assinado E2E"]))
    s.coord.post(f"/api/monografias/{mid}/documentos/{doc['id']}/validar-assinatura/")
    aguardar(lambda: s.aluno.get(f"/api/monografias/{mid}/").json()["status"] == "publicada", 60, 1, "publicação")

    # 8. busca pública encontra o TCC (inclusive por palavra do corpo); cache HIT na 2ª busca
    publico = Sessao(GW)
    aguardar(
        lambda: publico.get(f"/api/repositorio/monografias/?busca={s.termo_unico}&nc={uuid.uuid4().hex[:8]}").json()[
            "count"
        ]
        == 1,
        60,
        1,
        "indexação",
    )
    params = f"?busca={s.termo_unico}&ordenar=relevancia&x={uuid.uuid4().hex[:4]}"
    r1 = publico.get("/api/repositorio/monografias/" + params)
    r2 = publico.get("/api/repositorio/monografias/" + params)
    assert r1.headers["X-Cache"] == "MISS" and "HIT" in (
        r2.headers.get("X-Cache", "") + r2.headers.get("X-Proxy-Cache", "")
    )
    aguardar(
        lambda: s.mail.mensagens(s.aluno.perfil["email"])
        and any(
            "publicado" in m["Content"]["Headers"]["Subject"][0].lower()
            for m in s.mail.mensagens(s.aluno.perfil["email"])
        ),
        60,
        1,
        "e-mail de publicação",
    )

    # 9. dashboard reflete os números
    resumo = s.coord.get("/api/relatorios/resumo/").json()["dados"]
    assert resumo["por_status"].get("publicada", 0) >= 1


def test_negativos(s):
    publico = Sessao(GW)
    # anônimo não acessa restritos
    for url in [
        "/api/monografias/",
        "/api/bancas/",
        "/api/auth/me/",
        "/api/relatorios/resumo/",
        "/api/notificacoes/minhas/",
    ]:
        assert publico.get(url, esperado=None).status_code == 401, url
    # PDF inválido (texto renomeado)
    m = s.aluno.post("/api/monografias/", json={"titulo": "Negativo", "orientador_id": s.orientador_id}).json()
    r = s.aluno.post(
        f"/api/monografias/{m['id']}/arquivo/",
        files={"arquivo": ("x.pdf", b"texto puro", "application/pdf")},
        esperado=None,
    )
    assert r.status_code == 415
    # agendar banca sem aprovação do orientador
    r = s.coord.post(
        "/api/bancas/",
        json={
            "monografia_id": m["id"],
            "data_hora_inicio": datetime.now(UTC).isoformat(),
            "local": "Sala",
            "membros": [],
        },
        esperado=None,
    )
    assert r.status_code in (404, 409)
    # excluir publicada
    pub = publico.get("/api/repositorio/monografias/").json()["results"][0]["id"]
    adm = Sessao.login(GW, "admin@tcc.local", SENHA)
    r = adm.delete(f"/api/monografias/{pub}/", esperado=None)
    assert r.status_code == 409 and r.json()["codigo"] == "monografia_publicada_imutavel"
    # IDOR: outro aluno não vê a monografia
    outro = Sessao.login(GW, f"aluno1@{D}", SENHA)
    assert outro.get(f"/api/monografias/{m['id']}/", esperado=None).status_code == 403
    s.aluno.delete(f"/api/monografias/{m['id']}/")

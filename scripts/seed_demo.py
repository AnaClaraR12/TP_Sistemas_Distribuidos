"""Seed de demonstração — popula o sistema PELA API (via gateway), exercitando os fluxos reais.

Cria: 1 admin, 2 cursos (2 coordenadores), 10 professores (2 deles coordenadores), 20 alunos,
~40 monografias em estados variados e 5 bancas com avaliações (3 publicadas, 1 aprovada aguardando
termo, 1 reprovada). Senha de TODOS os usuários de demo: SEED_SENHA_PADRAO (padrão Demo@Tcc#2026).

Uso (com o sistema de pé):  python scripts/seed_demo.py --gateway http://localhost:8080
Requer acesso ao `docker compose` (para criar o admin e definir as senhas de demo).
"""

from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tcc_cliente import ErroApi, MailHog, Sessao, aguardar, pdf_simples  # noqa: E402

SENHA = os.environ.get("SEED_SENHA_PADRAO", "Demo@Tcc#2026")
DOMINIO = "demo.tcc.br"
ADMIN = "admin@tcc.local"
PARECER = "Trabalho bem estruturado, com fundamentação teórica adequada, metodologia clara e resultados coerentes."
TEMAS = [
    (
        "Sistemas distribuídos com microsserviços e filas de eventos",
        ["sistemas distribuídos", "microsserviços", "rabbitmq"],
    ),
    ("Cache distribuído com Redis em aplicações web de alta demanda", ["redis", "cache", "escalabilidade"]),
    ("Busca textual com PostgreSQL Full-Text Search", ["postgresql", "busca textual", "índices"]),
    (
        "Aprendizado de máquina para classificação de documentos acadêmicos",
        ["aprendizado de máquina", "classificação", "nlp"],
    ),
    ("Segurança em APIs REST com JWT e OAuth2", ["segurança", "jwt", "api rest"]),
    ("Orquestração de contêineres com Docker e Kubernetes", ["docker", "kubernetes", "devops"]),
    ("Computação em nuvem e elasticidade de recursos", ["nuvem", "elasticidade", "custos"]),
    ("Internet das Coisas aplicada à agricultura de precisão", ["iot", "agricultura", "sensores"]),
    ("Blockchain para rastreabilidade de documentos", ["blockchain", "rastreabilidade", "integridade"]),
    ("Acessibilidade em sistemas web governamentais", ["acessibilidade", "wcag", "governo eletrônico"]),
]
NOMES = [
    "Ana",
    "Bruno",
    "Carla",
    "Diego",
    "Elisa",
    "Fábio",
    "Gabriela",
    "Heitor",
    "Isabela",
    "João",
    "Karina",
    "Lucas",
    "Marina",
    "Nícolas",
    "Olívia",
    "Paulo",
    "Queila",
    "Rafael",
    "Sofia",
    "Thiago",
]
SOBRENOMES = ["Souza", "Lima", "Pereira", "Costa", "Almeida", "Ribeiro", "Gomes", "Martins", "Araújo", "Barbosa"]


def compose(*args: str) -> None:
    cmd = ["docker", "compose", "exec", "-T", "auth-service", "python", "manage.py", *args]
    print("  $", " ".join(cmd[:7]), "...")
    subprocess.run(cmd, check=True)


def pdf_tcc(titulo: str, autor: str, extra: str = "") -> bytes:
    return pdf_simples(
        [
            titulo,
            f"Autor: {autor}",
            "Resumo do trabalho de conclusão de curso.",
            f"Identificador {random.randint(10**8, 10**9)}",
            extra,
        ]
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", default="http://localhost:8080")
    ap.add_argument("--mailhog", default="http://localhost:8025")
    ap.add_argument("--sem-docker", action="store_true", help="não chama docker compose (admin/senhas já existem)")
    a = ap.parse_args()
    random.seed(42)
    gw, mail = a.gateway, MailHog(a.mailhog)

    print("1) Administrador")
    if not a.sem_docker:
        compose("garantir_admin", "--email", ADMIN, "--senha", SENHA)
    adm = Sessao.login(gw, ADMIN, SENHA)

    print("2) Professores e cursos")
    profs = []
    for i in range(10):
        nome = f"Prof. {NOMES[(i * 3) % 20]} {SOBRENOMES[i]}"
        email = f"prof{i + 1}@{DOMINIO}"
        r = adm.post(
            "/api/auth/professores/",
            json={
                "nome": nome,
                "email": email,
                "departamento": "DECOM" if i % 2 else "DCET",
                "area_pesquisa": TEMAS[i][1][0],
            },
            esperado=(201, 400, 409),
        )
        if r.status_code != 201:
            r = adm.get("/api/auth/professores/?limit=50")
            profs.append(next(p for p in r.json()["results"] if p["email"] == email))
        else:
            profs.append(r.json())
    cursos = []
    for nome, codigo, coord in [("Sistemas de Informação", "SI", profs[0]), ("Ciência da Computação", "CC", profs[1])]:
        r = adm.post(
            "/api/auth/cursos/", json={"nome": nome, "codigo": codigo, "coordenador": coord["id"]}, esperado=(201, 400)
        )
        cursos.append(
            r.json()
            if r.status_code == 201
            else next(c for c in adm.get("/api/auth/cursos/").json()["results"] if c["codigo"] == codigo)
        )

    print("3) Alunos")
    alunos = []
    for i in range(20):
        nome = f"{NOMES[i]} {SOBRENOMES[(i * 7) % 10]}"
        email = f"aluno{i + 1}@{DOMINIO}"
        r = adm.post(
            "/api/auth/alunos/",
            json={
                "nome": nome,
                "matricula": f"2022{i + 1:04d}",
                "email": email,
                "curso": cursos[i % 2]["id"],
                "orientador_atual": profs[2 + (i % 8)]["id"],
            },
            esperado=(201, 400, 409),
        )
        alunos.append({"email": email, "nome": nome, "orientador": profs[2 + (i % 8)], "curso": cursos[i % 2]})

    print("4) Senhas de demonstração")
    if not a.sem_docker:
        compose("definir_senhas_demo", "--dominio", DOMINIO, "--senha", SENHA, "--confirmar")

    print("5) Aguardando propagação dos cadastros (eventos cadastro.*)")
    aguardar(
        lambda: len(Sessao(gw).get("/api/repositorio/orientadores/").json()) >= 10, 90, 2, "read models de professores"
    )

    sess_prof = {p["email"]: Sessao.login(gw, p["email"], SENHA) for p in profs}
    # cada coordenador só enxerga as bancas do próprio curso
    coord_do_curso = {"SI": sess_prof[profs[0]["email"]], "CC": sess_prof[profs[1]["email"]]}

    print("6) Monografias (~40) em estados variados")
    monos = []
    for i, al in enumerate(alunos):
        s = Sessao.login(gw, al["email"], SENHA)
        aguardar(
            lambda s=s: s.post(
                "/api/monografias/", json={"titulo": "sonda", "orientador_id": al["orientador"]["id"]}, esperado=(201,)
            ).json(),
            60,
            2,
            "read model do aluno",
        )  # sonda: cria e apaga
        sondas = s.get("/api/monografias/?busca=sonda").json()["results"]
        for x in sondas:
            s.delete(f"/api/monografias/{x['id']}/")
        for k in range(2):
            titulo, palavras = TEMAS[(i + k * 5) % 10]
            titulo = f"{titulo} — estudo {i + 1}.{k + 1}"
            m = s.post(
                "/api/monografias/",
                json={
                    "titulo": titulo,
                    "resumo": f"Este trabalho investiga {titulo.lower()}.",
                    "palavras_chave": palavras,
                    "orientador_id": al["orientador"]["id"],
                },
            ).json()
            monos.append({"id": m["id"], "aluno": s, "al": al, "titulo": titulo, "etapa": "rascunho"})

    random.shuffle(monos)
    alvo_submeter = monos[:25]
    for m in alvo_submeter:
        m["aluno"].upload(m["id"], pdf_tcc(m["titulo"], m["al"]["nome"], "texto do corpo com o termo quiescente"))
        m["aluno"].post(f"/api/monografias/{m['id']}/submeter/", esperado=(202,))
        m["etapa"] = "em_avaliacao"
    print("   aguardando extração de texto...")
    for m in alvo_submeter:
        aguardar(
            lambda m=m: m["aluno"].get(f"/api/monografias/{m['id']}/").json()["texto_extraido"], 120, 2, "extração"
        )

    alvo_aprovar = alvo_submeter[:13]
    for m in alvo_aprovar:
        sess_prof[m["al"]["orientador"]["email"]].post(f"/api/monografias/{m['id']}/aprovar-orientador/")
        m["etapa"] = "aprovada_orientador"
    for m in alvo_submeter[13:15]:
        sess_prof[m["al"]["orientador"]["email"]].post(
            f"/api/monografias/{m['id']}/rejeitar-orientador/",
            json={"motivo": "Revise a metodologia e as referências."},
        )

    print("7) Bancas (5) com avaliações")
    inicio = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
    resultados = ["publicar", "publicar", "publicar", "aguardar_termo", "reprovar"]
    for n, (m, destino) in enumerate(zip(alvo_aprovar[:5], resultados, strict=True)):
        orientador = m["al"]["orientador"]
        outros = [p for p in profs[2:] if p["id"] != orientador["id"]]
        membro_interno = outros[n % len(outros)]
        externo_email = f"externo{n + 1}@{DOMINIO}"
        coord = coord_do_curso[m["al"]["curso"]["codigo"]]
        banca = aguardar(
            lambda m=m, coord=coord: coord.post(
                "/api/bancas/",
                json={
                    "monografia_id": m["id"],
                    "data_hora_inicio": (inicio + timedelta(hours=3 * n)).isoformat(),
                    "local": f"Sala {101 + n}",
                    "membros": [
                        {"tipo": "interno", "professor_id": membro_interno["id"]},
                        {
                            "tipo": "externo",
                            "nome": f"Dr(a). Externo {n + 1}",
                            "email": externo_email,
                            "instituicao": "UFMG",
                        },
                    ],
                },
                esperado=(201,),
            ).json(),
            60,
            2,
            "monografia apta no bancas-service",
        )
        token = aguardar(lambda e=externo_email: mail.token_convite(e), 90, 2, "e-mail de convite externo")
        for membro in banca["membros"]:
            if membro["tipo"] == "externo":
                Sessao(gw).post(
                    "/api/bancas/externo/confirmar/", json={"resposta": "confirmado"}, headers={"X-Banca-Token": token}
                )
            else:
                email = next(p["email"] for p in profs if p["id"] == membro["professor_id"])
                sess_prof[email].post(
                    f"/api/bancas/{banca['id']}/membros/{membro['id']}/confirmar/", json={"resposta": "confirmado"}
                )
        coord.post(f"/api/bancas/{banca['id']}/agendar/")
        coord.post(f"/api/bancas/{banca['id']}/marcar-realizada/")
        notas = {
            "publicar": [(9.0, "aprovado_sem_ressalvas")] * 3,
            "aguardar_termo": [(8.0, "aprovado_sem_ressalvas")] * 3,
            "reprovar": [(4.0, "reprovado"), (5.0, "reprovado"), (6.0, "aprovado_com_ressalvas")],
        }[destino]
        for membro, (nota, rec) in zip(banca["membros"], notas, strict=False):
            dados = {"nota": nota, "parecer": PARECER, "recomendacao": rec}
            if membro["tipo"] == "externo":
                Sessao(gw).post("/api/bancas/externo/avaliacao/", json=dados, headers={"X-Banca-Token": token})
            else:
                email = next(p["email"] for p in profs if p["id"] == membro["professor_id"])
                sess_prof[email].post(f"/api/bancas/{banca['id']}/avaliacoes/", json=dados)
        esperado = "reprovada" if destino == "reprovar" else "aprovada"
        aguardar(
            lambda m=m: m["aluno"].get(f"/api/monografias/{m['id']}/").json()["status"] == esperado, 90, 2, "resultado"
        )
        if destino == "publicar":
            doc = m["aluno"].documento(
                m["id"], "termo_autorizacao_publicacao", pdf_simples(["Termo de autorização assinado", m["titulo"]])
            )
            coord.post(f"/api/monografias/{m['id']}/documentos/{doc['id']}/validar-assinatura/")
            aguardar(
                lambda m=m: m["aluno"].get(f"/api/monografias/{m['id']}/").json()["status"] == "publicada",
                60,
                2,
                "publicação",
            )
        print(f"   banca {n + 1}: {destino}")

    aguardar(lambda: Sessao(gw).get("/api/repositorio/monografias/").json()["count"] >= 3, 90, 2, "indexação pública")
    print("\nSeed concluído!")
    print(f"  Admin:        {ADMIN} / {SENHA}")
    print(f"  Coordenador:  prof1@{DOMINIO} (SI), prof2@{DOMINIO} (CC) / {SENHA}")
    print(f"  Professores:  prof3..prof10@{DOMINIO} / {SENHA}")
    print(f"  Alunos:       aluno1..aluno20@{DOMINIO} / {SENHA}")


if __name__ == "__main__":
    try:
        main()
    except ErroApi as e:
        print("ERRO:", e)
        sys.exit(1)

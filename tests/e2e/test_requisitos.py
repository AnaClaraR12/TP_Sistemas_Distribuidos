"""Verificação, requisito a requisito, do enunciado (Trabalho_SistemasDistribuidos_Monografias.pdf).

Roda contra o SISTEMA REAL (docker compose de pé + `make seed`), passando pelo gateway e
inspecionando Redis, RabbitMQ e MailHog. Os testes são executados em ordem e compartilham estado.

    make up && make seed && pytest tests/e2e/test_requisitos.py -v
"""

import email.header
import hashlib
import os
import re
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from tcc_cliente import MailHog, Sessao, aguardar, pdf_simples  # noqa: E402

GW = os.environ.get("GATEWAY_URL", "http://localhost:8080")
RABBIT_API = os.environ.get("RABBIT_API", "http://localhost:15672/api")
RABBIT_AUTH = (os.environ.get("RABBITMQ_USER", "tcc"), os.environ.get("RABBITMQ_PASSWORD", "tcc-dev-123"))
SENHA = os.environ.get("SEED_SENHA_PADRAO", "Demo@Tcc#2026")
D = "demo.tcc.br"
PARECER = "Trabalho consistente, com metodologia adequada, revisão bibliográfica sólida e boa discussão dos resultados."
MAIL = MailHog(os.environ.get("MAILHOG_URL", "http://localhost:8025"))
DATA_BANCA = (datetime.now(UTC) + timedelta(days=120)).replace(hour=13, minute=0, second=0, microsecond=0)


def _no_ar() -> bool:
    try:
        return requests.get(f"{GW}/gateway/health", timeout=3).status_code == 200
    except requests.RequestException:
        return False


pytestmark = pytest.mark.skipif(not _no_ar(), reason=f"gateway {GW} indisponível (rode `make up && make seed`)")

E: dict = {}  # estado compartilhado entre os testes (executados em ordem)


# Utilitários
def compose(*args: str, check: bool = True) -> str:
    r = subprocess.run(["docker", "compose", *args], capture_output=True, text=True, timeout=300)
    if check and r.returncode != 0:
        raise RuntimeError(f"docker compose {' '.join(args)} falhou: {r.stderr[-800:]}")
    return r.stdout + r.stderr


def redis_cli(*args: str) -> str:
    return compose("exec", "-T", "redis", "redis-cli", *args).strip()


def fila(nome: str) -> dict:
    r = requests.get(f"{RABBIT_API}/queues/%2F/{requests.utils.quote(nome, safe='')}", auth=RABBIT_AUTH, timeout=10)
    r.raise_for_status()
    return r.json()


def assuntos(destinatario: str) -> list[str]:
    saida = []
    for m in MAIL.mensagens(destinatario):
        bruto = m["Content"]["Headers"].get("Subject", [""])[0]
        partes = email.header.decode_header(bruto)
        saida.append("".join(p.decode(c or "utf-8") if isinstance(p, bytes) else p for p, c in partes))
    return saida


def recebeu(destinatario: str, trecho: str, timeout: int = 90) -> bool:
    return bool(
        aguardar(
            lambda: any(trecho.lower() in a.lower() for a in assuntos(destinatario)),
            timeout,
            2,
            f"e-mail '{trecho}' para {destinatario}",
        )
    )


def login(email_: str) -> Sessao:
    return Sessao.login(GW, email_, SENHA)


def mono(sess: Sessao, mid: str) -> dict:
    return sess.get(f"/api/monografias/{mid}/").json()


def pdf_unico(rotulo: str, extra: str = "") -> bytes:
    return pdf_simples([f"Monografia de verificação {rotulo}", f"id {uuid.uuid4().hex}", extra])


def criar_rascunho(aluno: Sessao, titulo: str, palavras: list[str] | None = None) -> str:
    orientador = aluno.perfil["vinculos"]["aluno"]["orientador_atual"]["id"]
    r = aluno.post(
        "/api/monografias",
        json={  # sem barra final, como no exemplo do enunciado
            "titulo": titulo,
            "resumo": f"Resumo de {titulo}.",
            "palavras_chave": palavras or ["verificação", "sistemas distribuídos", "e2e"],
            "orientador_id": orientador,
        },
        esperado=(201,),
    )
    return r.json()["id"]


def submeter_e_aprovar(aluno: Sessao, orientador: Sessao, mid: str, conteudo: bytes) -> None:
    aluno.upload(mid, conteudo)
    aluno.post(f"/api/monografias/{mid}/submeter/", esperado=(202,))
    aguardar(lambda: mono(aluno, mid)["texto_extraido"], 120, 2, "extração de texto")
    orientador.post(f"/api/monografias/{mid}/aprovar-orientador/")


def token_externo(email_: str) -> str:
    return aguardar(lambda: MAIL.token_convite(email_), 90, 2, f"convite externo para {email_}")


def confirmar_todos(banca: dict, sessoes_prof: dict[str, Sessao], token: str | None) -> None:
    for m in banca["membros"]:
        if m["tipo"] == "externo":
            Sessao(GW).post(
                "/api/bancas/externo/confirmar/", json={"resposta": "confirmado"}, headers={"X-Banca-Token": token}
            )
        else:
            sessoes_prof[m["professor_id"]].post(
                f"/api/bancas/{banca['id']}/membros/{m['id']}/confirmar/", json={"resposta": "confirmado"}
            )


@pytest.fixture(scope="module")
def atores():
    """Usuários do seed: admin, coordenador de SI (prof1), alunos de SI e seus orientadores."""
    adm = login("admin@tcc.local")
    coord = login(f"prof1@{D}")
    profs = coord.get("/api/auth/professores/?limit=50").json()["results"]
    por_email = {p["email"]: p for p in profs}
    a = {"admin": adm, "coord": coord, "profs": por_email}
    for n in (1, 3, 5, 7, 9):  # alunos ímpares (índice par) são de Sistemas de Informação
        al = login(f"aluno{n}@{D}")
        oid = al.perfil["vinculos"]["aluno"]["orientador_atual"]["id"]
        oemail = next(e for e, p in por_email.items() if p["id"] == oid)
        a[f"aluno{n}"] = al
        a[f"ori{n}"] = login(oemail)
    a["prof10"] = login(f"prof10@{D}")
    a["prof4"] = login(f"prof4@{D}")
    a["sessoes_por_id"] = {}
    for chave in ("ori1", "ori3", "ori5", "prof10", "prof4"):
        a["sessoes_por_id"][a[chave].perfil["vinculos"]["professor"]["id"]] = a[chave]
    return a


# ============================================================================ ARQUITETURA


class TestMicrosservicos:
    """Arquitetura de microsserviços: 6 serviços independentes, cada um com sua API."""

    SERVICOS = ["auth", "monografias", "bancas", "repositorio", "notificacoes", "relatorios"]

    @pytest.mark.parametrize("svc", SERVICOS)
    def test_cada_servico_responde_pelo_gateway(self, svc):
        r = requests.get(f"{GW}/api/{svc}/health/?t={uuid.uuid4().hex}", timeout=10)
        assert r.status_code == 200 and r.json()["servico"] == f"{svc}-service"

    @pytest.mark.parametrize("svc", SERVICOS)
    def test_cada_servico_tem_api_propria_documentada(self, svc):
        r = requests.get(f"{GW}/api/{svc}/schema/?format=json&t={uuid.uuid4().hex}", timeout=20)
        assert r.status_code == 200 and "openapi" in r.text[:200]

    def test_um_banco_por_servico(self):
        saida = compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "postgres",
            "-tAc",
            "select datname from pg_database where datname like '%_db' order by 1",
        )
        assert saida.split() == [
            "auth_db",
            "bancas_db",
            "monografias_db",
            "notificacoes_db",
            "relatorios_db",
            "repositorio_db",
        ]

    def test_servico_nao_acessa_banco_de_outro(self):
        r = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "-e",
                "PGPASSWORD=" + os.environ.get("DB_PASSWORD_MONOGRAFIAS", "monografias-dev-123"),
                "postgres",
                "psql",
                "-h",
                "127.0.0.1",
                "-U",
                "monografias_user",
                "-d",
                "auth_db",
                "-c",
                "select 1",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert r.returncode != 0 and ("permission denied" in r.stderr.lower() or "permissão negada" in r.stderr.lower())


class TestFrontend:
    """Frontend em JavaScript consumindo a API; página principal."""

    def test_pagina_principal(self):
        r = requests.get(f"{GW}/", timeout=10)
        assert r.status_code == 200 and 'id="root"' in r.text
        js = re.search(r'src="(/assets/[^"]+\.js)"', r.text).group(1)
        assert requests.get(GW + js, timeout=10).status_code == 200

    def test_rotas_da_spa(self):
        for rota in ("/repositorio", "/login", "/dashboard", "/banca/externo/abc"):
            r = requests.get(GW + rota, timeout=10)
            assert r.status_code == 200 and 'id="root"' in r.text, rota

    def test_cabecalhos_de_seguranca(self):
        r = requests.get(f"{GW}/", timeout=10)
        assert "default-src 'self'" in r.headers.get("Content-Security-Policy", "")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"


# ============================================================================ PARTE 1 — AUTENTICAÇÃO


class TestAutenticacao:
    @pytest.mark.parametrize(
        "email_,papel",
        [
            ("admin@tcc.local", "admin"),
            (f"prof1@{D}", "coordenador"),
            (f"prof3@{D}", "professor"),
            (f"aluno1@{D}", "aluno"),
        ],
    )
    def test_login_e_senha_por_papel(self, email_, papel):
        assert login(email_).perfil["papel"] == papel

    def test_senha_errada_401(self):
        r = Sessao(GW).post("/api/auth/token/", json={"email": f"aluno2@{D}", "password": "errada"}, esperado=None)
        assert r.status_code == 401 and r.json()["codigo"] == "credenciais_invalidas"

    def test_bloqueio_apos_tentativas(self):
        for _ in range(5):
            Sessao(GW).post("/api/auth/token/", json={"email": f"aluno19@{D}", "password": "errada"}, esperado=None)
        r = Sessao(GW).post("/api/auth/token/", json={"email": f"aluno19@{D}", "password": SENHA}, esperado=None)
        assert r.status_code == 429 and r.json()["codigo"] == "conta_bloqueada"
        assert redis_cli("GET", f"login_falhas:aluno19@{D}") in ("5", "6")

    def test_senhas_criptografadas_com_argon2_e_politica(self):
        script = (
            "from django.contrib.auth import get_user_model as g;"
            "from django.contrib.auth.password_validation import validate_password as v;"
            f"print(g().objects.get(email='aluno1@{D}').password.split('$')[0]);"
            "import django.core.exceptions as e\n"
            "try:\n v('fraca123')\nexcept e.ValidationError: print('rejeitada')"
        )
        saida = compose("exec", "-T", "auth-service", "python", "manage.py", "shell", "-c", script)
        assert "argon2" in saida and "rejeitada" in saida

    def test_cadastro_publico_desabilitado(self):
        r = requests.post(
            f"{GW}/api/auth/contas/signup/",
            data={"email": "x@y.com", "password1": SENHA, "password2": SENHA},
            timeout=10,
            allow_redirects=False,
        )
        assert r.status_code in (200, 302, 403)
        assert (
            Sessao(GW).post("/api/auth/token/", json={"email": "x@y.com", "password": SENHA}, esperado=None).status_code
            == 401
        )

    def test_jwt_rs256_validado_por_outro_servico(self, atores):
        assert requests.get(f"{GW}/.well-known/jwks.json", timeout=10).json()["keys"][0]["alg"] == "RS256"
        assert atores["aluno1"].get("/api/monografias/").status_code == 200  # monografias valida o token do auth

    def test_logout_revoga_token(self):
        s = login(f"aluno2@{D}")
        s.post("/api/auth/logout/", json={}, esperado=(204,))
        assert s.get("/api/auth/me/", esperado=None).status_code == 401

    def test_dashboard_personalizado_por_tipo(self, atores):
        cfg = {k: atores[k].get("/api/auth/me/dashboard-config/").json() for k in ("admin", "coord", "aluno1", "ori1")}
        assert "nova_monografia" in [m["id"] for m in cfg["aluno1"]["menus"]]
        assert "pendencias_aprovacao" in cfg["ori1"]["widgets"]
        assert "grafico_por_curso" in cfg["coord"]["widgets"]
        assert "usuarios" in [m["id"] for m in cfg["admin"]["menus"]]


class TestControleDeAcesso:
    def test_anonimo_nao_acessa_restritos(self):
        for url in [
            "/api/monografias/",
            "/api/bancas/",
            "/api/avaliacoes/",
            "/api/auth/alunos/",
            "/api/auth/me/",
            "/api/auth/auditoria/",
            "/api/relatorios/resumo/",
            "/api/notificacoes/minhas/",
        ]:
            assert Sessao(GW).get(url, esperado=None).status_code == 401, url

    def test_permissoes_por_papel(self, atores):
        assert (
            atores["aluno1"].post("/api/auth/cursos/", json={"nome": "X", "codigo": "X1"}, esperado=None).status_code
            == 403
        )
        assert atores["aluno1"].get("/api/auth/auditoria/", esperado=None).status_code == 403
        assert atores["ori1"].post("/api/auth/alunos/", json={}, esperado=None).status_code == 403
        assert atores["ori1"].post("/api/monografias/", json={"titulo": "x"}, esperado=None).status_code == 403

    def test_area_admin_somente_rede_institucional(self, atores):
        assert requests.get(f"{GW}/admin/login/", timeout=10).status_code == 200  # host = rede institucional (.env)
        assert atores["admin"].get("/api/auth/admin/usuarios/").status_code == 200
        # de outro IP da rede Docker (fora de INSTITUTIONAL_CIDRS) => 403
        saida = compose(
            "exec",
            "-T",
            "frontend",
            "wget",
            "-S",
            "-q",
            "-O",
            "/dev/null",
            "http://gateway:8080/admin/login/",
            check=False,
        )
        assert "403" in saida
        saida = compose(
            "exec",
            "-T",
            "frontend",
            "wget",
            "-S",
            "-q",
            "-O",
            "/dev/null",
            "--header",
            f"Authorization: Bearer {atores['admin'].token}",
            "http://gateway:8080/api/auth/admin/usuarios/",
            check=False,
        )
        assert "403" in saida

    def test_spoof_de_ip_nao_burla_rede_institucional(self):
        saida = compose(
            "exec",
            "-T",
            "frontend",
            "wget",
            "-S",
            "-q",
            "-O",
            "/dev/null",
            "--header",
            "X-Real-IP: 127.0.0.1",
            "--header",
            "X-Forwarded-For: 127.0.0.1",
            "http://gateway:8080/admin/login/",
            check=False,
        )
        assert "403" in saida


# ============================================================================ PARTE 1 — CRUD DE CADASTROS


class TestCrudCadastros:
    def test_crud_curso_professor_aluno_com_eventos(self, atores):
        c = atores["coord"]
        sufixo = uuid.uuid4().hex[:5]
        curso = c.post("/api/auth/cursos/", json={"nome": f"Curso Verificação {sufixo}", "codigo": f"V{sufixo}"}).json()
        assert (
            c.patch(f"/api/auth/cursos/{curso['id']}/", json={"nome": f"Curso Verificado {sufixo}"})
            .json()["nome"]
            .startswith("Curso Verificado")
        )
        prof = c.post(
            "/api/auth/professores/",
            json={"nome": "Prof Temporário", "email": f"tmp{sufixo}@{D}", "departamento": "DX"},
        ).json()
        # coordenador não cadastra aluno em curso que não coordena
        r = c.post(
            "/api/auth/alunos/",
            json={"nome": "Fora", "matricula": f"F{sufixo}", "email": f"fora{sufixo}@{D}", "curso": curso["id"]},
            esperado=None,
        )
        assert r.status_code == 403
        meu_curso = c.perfil["vinculos"]["professor"]["cursos_coordenados"][0]["id"]
        aluno = c.post(
            "/api/auth/alunos/",
            json={
                "nome": "Aluno Temporário",
                "matricula": f"T{sufixo}",
                "email": f"al{sufixo}@{D}",
                "curso": meu_curso,
                "orientador_atual": prof["id"],
            },
        ).json()
        assert (
            c.patch(f"/api/auth/alunos/{aluno['id']}/", json={"nome": "Aluno Renomeado"}).json()["nome"]
            == "Aluno Renomeado"
        )
        # evento cadastro.* chega ao repositório (read model público)
        aguardar(
            lambda: any(
                x["id"] == curso["id"]
                for x in Sessao(GW).get(f"/api/repositorio/cursos/?nc={uuid.uuid4().hex[:8]}").json()
            ),
            60,
            2,
            "curso no repositório",
        )
        # e-mail "defina sua senha" para a conta criada
        assert recebeu(f"al{sufixo}@{D}", "Defina sua senha")
        assert c.delete(f"/api/auth/alunos/{aluno['id']}/").status_code == 204
        assert c.delete(f"/api/auth/professores/{prof['id']}/").status_code == 204
        assert c.delete(f"/api/auth/cursos/{curso['id']}/").status_code == 204
        aguardar(
            lambda: all(
                x["id"] != curso["id"]
                for x in Sessao(GW).get(f"/api/repositorio/cursos/?nc={uuid.uuid4().hex[:8]}").json()
            ),
            60,
            2,
            "exclusão propagada",
        )


# ============================================================================ PARTE 1 — SUBMISSÃO


class TestSubmissao:
    def test_rascunho_com_orientador(self, atores):
        E["m1"] = criar_rascunho(atores["aluno1"], f"Sistemas distribuidos verificados {uuid.uuid4().hex[:6]}")
        m = mono(atores["aluno1"], E["m1"])
        assert (
            m["status"] == "rascunho"
            and m["orientador_id"] == atores["aluno1"].perfil["vinculos"]["aluno"]["orientador_atual"]["id"]
        )

    def test_edicao_em_rascunho_e_historico(self, atores):
        al = atores["aluno1"]
        al.patch(f"/api/monografias/{E['m1']}/", json={"resumo": "Resumo revisado pelo aluno."})
        h = al.get(f"/api/monografias/{E['m1']}/historico/").json()["historico"]
        assert h[0]["usuario_id"] == al.perfil["id"]
        assert any(x["campo"] == "resumo" and x["novo"] == "Resumo revisado pelo aluno." for x in h[0]["alteracoes"])
        assert h[0]["data_hora"]

    def test_somente_pdf(self, atores):
        r = atores["aluno1"].post(
            f"/api/monografias/{E['m1']}/arquivo/",
            files={"arquivo": ("tcc.pdf", b"isto e texto renomeado", "application/pdf")},
            esperado=None,
        )
        assert r.status_code == 415 and r.json()["codigo"] == "formato_invalido"

    def test_tamanho_maximo_50mb(self, atores):
        grande = b"%PDF-1.4\n" + os.urandom(51 * 1024 * 1024)
        r = atores["aluno1"].post(
            f"/api/monografias/{E['m1']}/arquivo/",
            files={"arquivo": ("g.pdf", grande, "application/pdf")},
            esperado=None,
        )
        assert r.status_code == 413

    def test_upload_com_sha256(self, atores):
        E["palavra_corpo"] = "zeugma" + uuid.uuid4().hex[:8]
        E["pdf_m1"] = pdf_unico("m1", f"texto do corpo {E['palavra_corpo']}")
        r = atores["aluno1"].upload(E["m1"], E["pdf_m1"])
        assert r.status_code == 201
        assert r.json()["arquivo_sha256"] == hashlib.sha256(E["pdf_m1"]).hexdigest()
        assert r.json()["status"] == "rascunho"  # upload não muda o status

    def test_deduplicacao_por_hash(self, atores):
        E["m3"] = criar_rascunho(atores["aluno3"], f"Conflitos de banca {uuid.uuid4().hex[:6]}")
        r = atores["aluno3"].post(
            f"/api/monografias/{E['m3']}/arquivo/",
            files={"arquivo": ("c.pdf", E["pdf_m1"], "application/pdf")},
            esperado=None,
        )
        assert r.status_code == 409 and r.json()["codigo"] == "arquivo_duplicado"

    def test_banca_bloqueada_sem_aprovacao_do_orientador(self, atores):
        r = atores["coord"].post(
            "/api/bancas",
            json={
                "monografia_id": E["m1"],
                "data_hora_inicio": DATA_BANCA.isoformat(),
                "local": "Sala 1",
                "membros": [],
            },
            esperado=None,
        )
        assert r.status_code == 409 and r.json()["codigo"] == "orientador_nao_aprovou"

    def test_submissao_assincrona(self, atores):
        al = atores["aluno1"]
        t0 = time.perf_counter()
        r = al.post(f"/api/monografias/{E['m1']}/submeter/", esperado=(202,))
        assert time.perf_counter() - t0 < 1.0
        assert r.json()["status"] == "em_avaliacao" and r.json()["texto_extraido"] is False  # não extraiu na requisição
        aguardar(lambda: mono(al, E["m1"])["texto_extraido"], 120, 1, "extração assíncrona")
        assert redis_cli("EXISTS", f"upload_em_andamento:{E['m1']}") == "0"  # lock liberado pelo evento texto_extraido

    def test_upload_em_andamento_bloqueia_reenvio(self, atores):
        redis_cli("SET", f"upload_em_andamento:{E['m1']}", "simulado", "EX", "30")
        r = atores["aluno1"].post(f"/api/monografias/{E['m1']}/submeter/", esperado=None)
        redis_cli("DEL", f"upload_em_andamento:{E['m1']}")
        assert r.status_code == 409 and r.json()["codigo"] == "upload_em_andamento"

    def test_fluxo_exemplo_notifica_orientador(self, atores):
        oemail = atores["ori1"].perfil["email"]
        assert recebeu(oemail, "Nova submissão")
        assert recebeu(oemail, "Arquivo processado")

    def test_acompanhamento_de_status_e_aprovacao(self, atores):
        assert mono(atores["aluno1"], E["m1"])["aprovacao_orientador"] == "pendente"
        assert atores["prof4"].post(f"/api/monografias/{E['m1']}/aprovar-orientador/", esperado=None).status_code == 403
        r = atores["ori1"].post(f"/api/monografias/{E['m1']}/aprovar-orientador/")
        assert (
            r.json()["aprovacao_orientador"] == "aprovada"
            and r.json()["arquivo_sha256_aprovado"] == hashlib.sha256(E["pdf_m1"]).hexdigest()
        )
        assert recebeu(atores["aluno1"].perfil["email"], "Aprovada pelo orientador")

    def test_arquivo_imutavel_apos_aprovacao(self, atores):
        r = atores["aluno1"].post(
            f"/api/monografias/{E['m1']}/arquivo/",
            files={"arquivo": ("n.pdf", pdf_unico("x"), "application/pdf")},
            esperado=None,
        )
        assert r.status_code == 409

    def test_busca_restrita_por_filtros(self, atores):
        c, al = atores["coord"], atores["aluno1"]
        aid = al.perfil["vinculos"]["aluno"]["id"]
        oid = al.perfil["vinculos"]["aluno"]["orientador_atual"]["id"]
        cid = al.perfil["vinculos"]["aluno"]["curso"]["id"]
        for q in (
            f"aluno={aid}",
            f"orientador={oid}",
            f"curso={cid}",
            "palavras_chave=verificação",
            "busca=sistemas+distribuidos",
        ):
            ids = [m["id"] for m in c.get(f"/api/monografias?{q}&limit=50").json()["results"]]
            assert E["m1"] in ids, q


# ============================================================================ PARTE 1 — BANCAS


class TestBancas:
    def test_preparar_segunda_monografia(self, atores):
        submeter_e_aprovar(atores["aluno3"], atores["ori3"], E["m3"], pdf_unico("m3"))

    def test_agendamento_e_confirmacoes(self, atores):
        c = atores["coord"]
        E["ext1"] = f"ext-{uuid.uuid4().hex[:6]}@{D}"
        b = c.post(
            "/api/bancas",
            json={
                "monografia_id": E["m1"],
                "data_hora_inicio": DATA_BANCA.isoformat(),
                "local": "Auditório 2",
                "membros": [
                    {"tipo": "interno", "professor_id": atores["prof10"].perfil["vinculos"]["professor"]["id"]},
                    {"tipo": "externo", "nome": "Dra. Externa", "email": E["ext1"], "instituicao": "UFMG"},
                ],
            },
            esperado=(201,),
        ).json()
        E["b1"] = b
        assert b["status"] == "em_organizacao" and len(b["membros"]) == 3
        r = c.post(f"/api/bancas/{b['id']}/agendar/", esperado=None)
        assert r.status_code == 409 and r.json()["codigo"] == "confirmacoes_pendentes"
        E["tok1"] = token_externo(E["ext1"])
        confirmar_todos(b, atores["sessoes_por_id"], E["tok1"])
        assert c.post(f"/api/bancas/{b['id']}/agendar/").json()["status"] == "agendada"

    def test_notificacao_a_todos_os_membros_e_aluno(self, atores):
        for email_ in (
            atores["aluno1"].perfil["email"],
            atores["ori1"].perfil["email"],
            atores["prof10"].perfil["email"],
            E["ext1"],
        ):
            assert recebeu(email_, "agendada"), email_

    def test_conflito_de_horario(self, atores):
        c = atores["coord"]
        E["ext3"] = f"ext-{uuid.uuid4().hex[:6]}@{D}"
        b = c.post(
            "/api/bancas",
            json={
                "monografia_id": E["m3"],
                "data_hora_inicio": (DATA_BANCA + timedelta(hours=1)).isoformat(),
                "link": "https://meet.exemplo.br/verificacao",
                "membros": [
                    {"tipo": "interno", "professor_id": atores["prof10"].perfil["vinculos"]["professor"]["id"]},
                    {"tipo": "externo", "nome": "Dr. Externo", "email": E["ext3"]},
                ],
            },
            esperado=(201,),
        ).json()
        E["b3"] = b
        E["tok3"] = token_externo(E["ext3"])
        confirmar_todos(b, atores["sessoes_por_id"], E["tok3"])
        r = c.post(f"/api/bancas/{b['id']}/agendar/", esperado=None)
        assert r.status_code == 409 and r.json()["codigo"] == "conflito_horario"
        assert r.json()["detalhes"]["conflitos"][0]["banca_id"] == E["b1"]["id"]

    def test_edicao_de_banca_nao_realizada(self, atores):
        c = atores["coord"]
        novo = (DATA_BANCA + timedelta(hours=5)).isoformat()
        r = c.patch(f"/api/bancas/{E['b3']['id']}/", json={"data_hora_inicio": novo})
        assert r.json()["status"] == "em_organizacao" and all(
            m["confirmacao"] == "pendente" for m in r.json()["membros"]
        )
        confirmar_todos(r.json(), atores["sessoes_por_id"], E["tok3"])
        assert c.post(f"/api/bancas/{E['b3']['id']}/agendar/").json()["status"] == "agendada"

    def test_token_externo_restrito(self, atores):
        pub = Sessao(GW)
        r = pub.get("/api/bancas/externo/minha-banca/", headers={"X-Banca-Token": E["tok1"]})
        assert r.json()["banca"]["id"] == E["b1"]["id"]
        assert (
            pub.get(f"/api/bancas/{E['b3']['id']}/", headers={"X-Banca-Token": E["tok1"]}, esperado=None).status_code
            == 401
        )
        assert (
            pub.get(
                "/api/bancas/externo/minha-banca/", headers={"X-Banca-Token": "falso" * 8}, esperado=None
            ).status_code
            == 401
        )
        pdf = requests.get(GW + r.json()["pdf_url"], timeout=30)
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    def test_avaliacao_so_apos_realizacao(self, atores):
        r = atores["ori3"].post(
            f"/api/bancas/{E['b3']['id']}/avaliacoes/",
            json={"nota": 8, "parecer": PARECER, "recomendacao": "aprovado_sem_ressalvas"},
            esperado=None,
        )
        assert r.status_code == 409 and r.json()["codigo"] == "banca_nao_realizada"

    def test_resultado_somente_com_todas_as_avaliacoes(self, atores):
        c, b = atores["coord"], E["b1"]
        c.post(f"/api/bancas/{b['id']}/marcar-realizada/")
        a1 = (
            atores["ori1"]
            .post(
                f"/api/bancas/{b['id']}/avaliacoes/",
                json={"nota": 8, "parecer": PARECER, "recomendacao": "aprovado_sem_ressalvas"},
            )
            .json()
        )
        atores["prof10"].post(
            f"/api/bancas/{b['id']}/avaliacoes/",
            json={"nota": 9, "parecer": PARECER, "recomendacao": "aprovado_sem_ressalvas"},
        )
        # edição pelo próprio avaliador antes do fechamento; outro membro não edita
        assert (
            atores["ori1"].patch(f"/api/bancas/{b['id']}/avaliacoes/{a1['id']}/", json={"nota": "8.5"}).json()["nota"]
            == "8.5"
        )
        assert atores["prof10"].patch(f"/api/avaliacoes/{a1['id']}/", json={"nota": 1}, esperado=None).status_code in (
            403,
            404,
        )
        r = atores["ori1"].post(
            f"/api/bancas/{b['id']}/avaliacoes/",
            json={"nota": 7, "parecer": PARECER, "recomendacao": "aprovado_sem_ressalvas"},
            esperado=None,
        )
        assert r.status_code == 409 and r.json()["codigo"] == "avaliacao_duplicada"
        time.sleep(8)
        assert c.get(f"/api/bancas/{b['id']}/").json()["resultado_final"] is None  # 2 de 3: não calcula
        assert mono(atores["aluno1"], E["m1"])["status"] == "em_avaliacao"
        Sessao(GW).post(
            "/api/bancas/externo/avaliacao/",
            json={"nota": 9.5, "parecer": PARECER, "recomendacao": "aprovado_sem_ressalvas"},
            headers={"X-Banca-Token": E["tok1"]},
        )
        aguardar(
            lambda: c.get(f"/api/bancas/{b['id']}/").json()["resultado_final"] == "aprovada",
            90,
            2,
            "resultado calculado",
        )
        banca = c.get(f"/api/bancas/{b['id']}/").json()
        assert banca["media_final"] == "9.00"  # (8,5 + 9 + 9,5) / 3
        aguardar(
            lambda: mono(atores["aluno1"], E["m1"])["status"] == "aprovada", 90, 2, "status atualizado na monografia"
        )
        assert recebeu(atores["aluno1"].perfil["email"], "Resultado da banca")
        E["a1"] = a1

    def test_avaliacao_bloqueada_apos_fechamento_e_token_revogado(self, atores):
        r = atores["ori1"].patch(
            f"/api/bancas/{E['b1']['id']}/avaliacoes/{E['a1']['id']}/", json={"nota": 2}, esperado=None
        )
        assert r.status_code == 409 and r.json()["codigo"] == "resultado_fechado"
        r = Sessao(GW).get("/api/bancas/externo/minha-banca/", headers={"X-Banca-Token": E["tok1"]}, esperado=None)
        assert r.status_code == 401 and r.json()["codigo"] == "token_revogado"
        assert (
            atores["coord"].patch(f"/api/bancas/{E['b1']['id']}/", json={"local": "Outra"}, esperado=None).status_code
            == 409
        )

    def test_cancelamento_e_exclusao_de_banca(self, atores):
        c = atores["coord"]
        cand = [
            m
            for m in c.get("/api/monografias/?status=em_avaliacao&aprovacao_orientador=aprovada&limit=50").json()[
                "results"
            ]
            if not c.get(f"/api/bancas/?monografia={m['id']}").json()["results"]
        ]
        assert cand, "seed deveria deixar monografias aprovadas sem banca"
        mid = cand[0]["id"]
        prof = next(
            p
            for p in atores["profs"].values()
            if p["id"] != cand[0]["orientador_id"] and p["email"].startswith("prof1") is False
        )
        b = c.post(
            "/api/bancas/",
            json={
                "monografia_id": mid,
                "data_hora_inicio": (DATA_BANCA + timedelta(days=3)).isoformat(),
                "local": "Sala 9",
                "membros": [
                    {"tipo": "interno", "professor_id": prof["id"]},
                    {"tipo": "externo", "nome": "Ext", "email": f"c{uuid.uuid4().hex[:5]}@{D}"},
                ],
            },
        ).json()
        assert (
            c.post(f"/api/bancas/{b['id']}/cancelar/", json={"motivo": "Teste de cancelamento"}).json()["status"]
            == "cancelada"
        )
        assert c.delete(f"/api/bancas/{b['id']}/").status_code == 204


# ============================================================================ PARTE 1 — PUBLICAÇÃO


class TestPublicacao:
    def test_publicacao_automatica_apos_termo(self, atores):
        al = atores["aluno1"]
        doc = al.documento(E["m1"], "termo_autorizacao_publicacao", pdf_unico("termo m1"))
        assert mono(al, E["m1"])["status"] == "aprovada"  # termo ainda não validado
        atores["coord"].post(f"/api/monografias/{E['m1']}/documentos/{doc['id']}/validar-assinatura/")
        aguardar(lambda: mono(al, E["m1"])["status"] == "publicada", 60, 2, "publicação automática")
        assert recebeu(al.perfil["email"], "publicado")

    def test_publicada_nunca_excluida_nem_editada(self, atores):
        r = atores["admin"].delete(f"/api/monografias/{E['m1']}/", esperado=None)
        assert r.status_code == 409 and r.json()["codigo"] == "monografia_publicada_imutavel"
        assert (
            atores["aluno1"].patch(f"/api/monografias/{E['m1']}/", json={"titulo": "x"}, esperado=None).status_code
            == 409
        )

    def test_ressalvas_exigem_versao_corrigida(self, atores):
        c, b = atores["coord"], E["b3"]
        c.post(f"/api/bancas/{b['id']}/marcar-realizada/")
        atores["ori3"].post(
            f"/api/bancas/{b['id']}/avaliacoes/",
            json={"nota": 8, "parecer": PARECER, "recomendacao": "aprovado_com_ressalvas"},
        )
        atores["prof10"].post(
            f"/api/bancas/{b['id']}/avaliacoes/",
            json={"nota": 8, "parecer": PARECER, "recomendacao": "aprovado_sem_ressalvas"},
        )
        Sessao(GW).post(
            "/api/bancas/externo/avaliacao/",
            json={"nota": 7.5, "parecer": PARECER, "recomendacao": "aprovado_sem_ressalvas"},
            headers={"X-Banca-Token": E["tok3"]},
        )
        al = atores["aluno3"]
        aguardar(lambda: mono(al, E["m3"])["status"] == "aprovada", 90, 2, "aprovada com ressalvas")
        assert mono(al, E["m3"])["exige_correcao"] is True
        doc = al.documento(E["m3"], "termo_autorizacao_publicacao", pdf_unico("termo m3"))
        c.post(f"/api/monografias/{E['m3']}/documentos/{doc['id']}/validar-assinatura/")
        m = mono(al, E["m3"])
        assert m["status"] == "aprovada" and "versao_corrigida" in m["pendencias_publicacao"]
        al.documento(E["m3"], "versao_corrigida", pdf_unico("corrigida m3"))
        assert mono(al, E["m3"])["status"] == "aprovada"  # falta o orientador validar
        atores["ori3"].post(f"/api/monografias/{E['m3']}/validar-correcao/")
        aguardar(lambda: mono(al, E["m3"])["status"] == "publicada", 60, 2, "publicação após correção")


# ============================================================================ PARTE 1 — REPOSITÓRIO PÚBLICO


class TestRepositorioPublico:
    def _ids(self, params: str) -> list[str]:
        r = requests.get(f"{GW}/api/repositorio/monografias/?{params}&limit=50&nc={uuid.uuid4().hex[:6]}", timeout=20)
        assert r.status_code == 200
        return [x["id"] for x in r.json()["results"]]

    def test_aparece_no_repositorio_publico(self):
        aguardar(lambda: E["m1"] in self._ids("ordenar=recentes"), 90, 2, "indexação pública")

    def test_pesquisavel_por_cada_criterio(self, atores):
        al = atores["aluno1"].perfil
        detalhe = requests.get(f"{GW}/api/repositorio/monografias/{E['m1']}/", timeout=10).json()
        criterios = {
            "titulo": "titulo=" + requests.utils.quote(detalhe["titulo"][:25]),
            "autor": "autor=" + requests.utils.quote(al["nome"]),
            "orientador": f"orientador={detalhe['orientador_id']}",
            "orientador (nome)": "orientador=" + requests.utils.quote(detalhe["orientador_nome"]),
            "curso": f"curso={detalhe['curso_id']}",
            "ano de defesa": f"ano_defesa={detalhe['ano_defesa']}",
            "palavras-chave": "palavras_chave=verificacao",
            "texto do PDF": f"busca={E['palavra_corpo']}",
        }
        for nome, q in criterios.items():
            assert E["m1"] in self._ids(q), nome
        assert detalhe["ano_defesa"] == DATA_BANCA.astimezone().year

    def test_leitura_publica_sem_autenticacao_e_download_integro(self):
        r = requests.get(f"{GW}/api/repositorio/monografias/{E['m1']}/download/", timeout=30)
        assert r.status_code == 200 and hashlib.sha256(r.content).hexdigest() == hashlib.sha256(E["pdf_m1"]).hexdigest()
        assert requests.post(f"{GW}/api/repositorio/monografias/", json={}, timeout=10).status_code in (401, 403, 405)

    def test_nao_publicadas_nao_aparecem(self, atores):
        rascunhos = atores["coord"].get("/api/monografias/?status=rascunho&limit=5").json()["results"]
        ids = self._ids("ordenar=recentes&limit=50")
        assert all(m["id"] not in ids for m in rascunhos)

    def test_endpoints_publicos_json(self):
        for url in ("/api/repositorio/cursos/", "/api/repositorio/orientadores/", "/api/repositorio/monografias/"):
            r = requests.get(GW + url, timeout=10)
            assert r.status_code == 200 and r.headers["Content-Type"].startswith("application/json"), url

    def test_cache_redis_hit_miss_e_chave_busca(self):
        q = f"/api/repositorio/monografias/?busca=sistemas&x={uuid.uuid4().hex[:6]}"
        r1, r2 = requests.get(GW + q, timeout=10), requests.get(GW + q, timeout=10)
        assert r1.headers["X-Cache"] == "MISS"
        assert "HIT" in (r2.headers.get("X-Cache", "") + r2.headers.get("X-Proxy-Cache", ""))
        assert re.search(r"^busca:\d+:[0-9a-f]{64}$", redis_cli("--scan", "--pattern", "busca:*:*"), re.M)


# ============================================================================ PARTE 1 — INTEGRIDADE


class TestIntegridade:
    def test_sha256_detecta_alteracao_nao_autorizada(self, atores):
        al, ori = atores["aluno5"], atores["ori5"]
        mid = criar_rascunho(al, f"Integridade {uuid.uuid4().hex[:6]}")
        conteudo = pdf_unico("integridade")
        submeter_e_aprovar(al, ori, mid, conteudo)
        assert ori.post(f"/api/monografias/{mid}/verificar-integridade/").json()["integridade_ok"] is True
        caminho = f"/app/media/monografias/{mid}/{hashlib.sha256(conteudo).hexdigest()}.pdf"
        compose("exec", "-T", "monografias-service", "sh", "-c", f"echo adulterado >> {caminho}")
        r = ori.post(f"/api/monografias/{mid}/verificar-integridade/").json()
        assert r["integridade_ok"] is False and r["sha_atual"] != r["sha_esperado"]
        aguardar(
            lambda: atores["admin"]
            .get(f"/api/auth/auditoria/?acao=integridade_violada&recurso_id={mid}")
            .json()["count"]
            >= 1,
            60,
            2,
            "auditoria crítica",
        )
        assert recebeu("admin@tcc.local", "integridade")


class TestRateLimit:
    def test_limite_de_submissoes(self, atores):
        al = atores["aluno7"]
        mid = criar_rascunho(al, f"Limite {uuid.uuid4().hex[:6]}")
        codigos = [al.upload(mid, pdf_unico(f"rl{i}"), esperado=None).status_code for i in range(7)]
        assert 429 in codigos and codigos[0] == 201
        assert redis_cli("--scan", "--pattern", "rl:submissao:*")


# ============================================================================ PARTE 2 — EVENTOS, REDIS, AUDITORIA


class TestFilaDeEventos:
    @pytest.mark.parametrize(
        "nome",
        [
            "repositorio.monografia.submetida",  # submissão -> extração e indexação
            "notificacoes.monografia.submetida",  # submissão -> notifica orientador
            "notificacoes.banca.agendada",  # agendamento -> notifica membros e aluno
            "bancas.avaliacao.registrada",  # avaliação -> verifica fechamento e calcula
            "monografias.banca.resultado_calculado",  # resultado -> atualiza status
            "repositorio.monografia.publicada",  # publicação -> indexa no repositório
            "notificacoes.monografia.publicada",  # publicação -> e-mail ao aluno
        ],
    )
    def test_fila_existe_tem_consumidor_e_processou(self, nome):
        q = fila(nome)
        assert q["durable"] and q["consumers"] >= 1
        assert q.get("message_stats", {}).get("ack", 0) >= 1, f"{nome} não processou mensagens"
        assert q["arguments"]["x-dead-letter-exchange"] == "tcc.dlx"
        assert fila(nome + ".dlq")["durable"] and fila(nome + ".retry.1")["arguments"]["x-message-ttl"] == 10000

    def test_exchange_topic(self):
        r = requests.get(f"{RABBIT_API}/exchanges/%2F/tcc.events", auth=RABBIT_AUTH, timeout=10).json()
        assert r["type"] == "topic" and r["durable"]


class TestAuditoriaEHistorico:
    def test_auditoria_centralizada_de_varios_servicos(self, atores):
        adm = atores["admin"]
        assert adm.get("/api/auth/auditoria/?acao=login").json()["count"] >= 1
        origens = {
            r["servico_origem"] for r in adm.get("/api/auth/auditoria/?limit=50&recurso=monografia").json()["results"]
        }
        assert "monografias-service" in origens
        assert adm.get("/api/auth/auditoria/?acao=banca_agendada").json()["count"] >= 1
        assert adm.get("/api/auth/auditoria/?acao=token_externo_usado").json()["count"] >= 1

    def test_historico_quem_o_que_quando(self, atores):
        h = atores["coord"].get(f"/api/bancas/{E['b3']['id']}/historico/").json()["historico"]
        alteracao = next(x for x in h if any(a["campo"] == "data_hora_inicio" for a in x["alteracoes"]))
        assert alteracao["usuario_id"] == atores["coord"].perfil["id"] and alteracao["data_hora"]


class TestDashboard:
    def test_relatorios_com_dados(self, atores):
        for nome in (
            "monografias-por-curso",
            "monografias-por-orientador",
            "monografias-por-ano-defesa",
            "taxa-aprovacao",
            "tempo-medio-submissao-defesa",
            "resumo",
        ):
            assert atores["admin"].get(f"/api/relatorios/{nome}/").status_code == 200, nome
        d = aguardar(
            lambda: (x := atores["admin"].get("/api/relatorios/resumo/").json()["dados"])["por_status"].get(
                "publicada", 0
            )
            >= 5
            and x,
            90,
            3,
            "fatos atualizados por eventos",
        )
        assert d["taxa_aprovacao"]["geral"]["taxa"] is not None
        assert d["tempo_medio_submissao_defesa"]["amostra"] >= 1
        assert {c["curso_nome"] for c in d["por_curso"]} >= {"Sistemas de Informação", "Ciência da Computação"}
        coord_total = atores["coord"].get("/api/relatorios/resumo/").json()["dados"]["total"]
        assert 0 < coord_total <= d["total"]  # coordenador vê só o escopo do seu curso


# ============================================================================ ESCALABILIDADE E RESILIÊNCIA


class TestEscalabilidade:
    def test_replicas_balanceadas_pelo_gateway(self):
        compose(
            "up",
            "-d",
            "--no-recreate",
            "--scale",
            "repositorio-service=3",
            "--wait",
            "--wait-timeout",
            "300",
            "repositorio-service",
        )
        time.sleep(15)  # o Nginx reconsulta o DNS do Docker a cada 10 s (resolver valid=10s)
        instancias = set()
        for i in range(60):
            r = requests.get(f"{GW}/api/repositorio/health/?r={i}-{uuid.uuid4().hex[:4]}", timeout=10)
            instancias.add(r.json()["instancia"])
        assert len(instancias) >= 2, instancias

    def test_rajada_de_buscas_sem_erros(self):
        termos = ["sistemas", "redis", "cache", "docker", "segurança", "nuvem", "iot", "blockchain"]

        def buscar(i):
            return requests.get(
                f"{GW}/api/repositorio/monografias/?busca={termos[i % len(termos)]}", timeout=30
            ).status_code

        with ThreadPoolExecutor(max_workers=50) as ex:
            codigos = list(ex.map(buscar, range(500)))
        assert codigos.count(200) == 500, {c: codigos.count(c) for c in set(codigos)}


class TestResiliencia:
    def test_servico_fora_nao_derruba_o_resto_e_eventos_sao_processados_na_volta(self, atores):
        al = atores["aluno9"]
        oemail = next(
            e for e, p in atores["profs"].items() if p["id"] == al.perfil["vinculos"]["aluno"]["orientador_atual"]["id"]
        )
        antes = sum("nova submissão" in a.lower() for a in assuntos(oemail))
        compose("stop", "notificacoes-worker")
        try:
            mid = criar_rascunho(al, f"Resiliência {uuid.uuid4().hex[:6]}")
            al.upload(mid, pdf_unico("resiliencia"))
            al.post(f"/api/monografias/{mid}/submeter/", esperado=(202,))
            assert requests.get(f"{GW}/api/repositorio/monografias/?busca=sistemas", timeout=10).status_code == 200
            aguardar(lambda: mono(al, mid)["texto_extraido"], 120, 2, "extração continua funcionando")
            aguardar(
                lambda: fila("notificacoes.monografia.submetida")["messages_ready"] >= 1,
                60,
                2,
                "evento acumulado na fila",
            )
        finally:
            compose("start", "notificacoes-worker")
        aguardar(
            lambda: fila("notificacoes.monografia.submetida")["messages_ready"] == 0, 120, 2, "fila drenada na volta"
        )
        aguardar(
            lambda: sum("nova submissão" in a.lower() for a in assuntos(oemail)) > antes,
            90,
            2,
            "e-mail entregue após a volta",
        )

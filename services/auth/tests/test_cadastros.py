"""CRUD de cursos/professores/alunos, eventos cadastro.*, papéis e histórico."""

import pytest
from django.core import mail

from tcc_common.testing import eventos_outbox

pytestmark = pytest.mark.django_db


@pytest.fixture
def coord(curso_com_coordenador, logar):
    curso, prof, _ = curso_com_coordenador
    c = logar("coord@ufvjm.edu.br")
    c.curso, c.prof = curso, prof
    return c


def test_criar_aluno_gera_user_e_evento(coord, django_capture_on_commit_callbacks):
    from apps.contas.models import User

    with django_capture_on_commit_callbacks(execute=True):
        r = coord.post(
            "/api/auth/alunos/",
            {
                "nome": "Maria Souza",
                "matricula": "2026010",
                "email": "Maria@ufvjm.edu.br",
                "curso": str(coord.curso.id),
                "orientador_atual": str(coord.prof.id),
            },
            format="json",
        )
    assert r.status_code == 201, r.data
    user = User.objects.get(email="maria@ufvjm.edu.br")
    assert user.papel == "aluno"
    assert not user.has_usable_password()  # senha temporária: definida pelo link
    assert user.groups.filter(name="Alunos").exists()
    assert len(mail.outbox) == 1 and "Defina sua senha" in mail.outbox[0].subject
    ev = eventos_outbox("cadastro.aluno.upserted")[-1]
    assert ev["data"]["matricula"] == "2026010"
    assert ev["data"]["orientador_id"] == str(coord.prof.id)
    assert ev["schema_version"] == 1 and ev["producer"] == "auth-service"


def test_email_duplicado_409(coord):
    payload = {"nome": "X", "matricula": "1", "email": "coord@ufvjm.edu.br", "curso": str(coord.curso.id)}
    r = coord.post("/api/auth/alunos/", payload, format="json")
    assert r.status_code == 400 or r.status_code == 409


def test_criar_professor_e_designar_coordenador(coord):
    from apps.contas.models import User

    r = coord.post(
        "/api/auth/professores/",
        {"nome": "Prof Novo", "email": "novo@ufvjm.edu.br", "departamento": "DECOM", "area_pesquisa": "Redes"},
        format="json",
    )
    assert r.status_code == 201
    assert User.objects.get(email="novo@ufvjm.edu.br").papel == "professor"
    r = coord.post(
        "/api/auth/cursos/", {"nome": "Engenharia", "codigo": "ENG", "coordenador": r.data["id"]}, format="json"
    )
    assert r.status_code == 201
    assert User.objects.get(email="novo@ufvjm.edu.br").papel == "coordenador"
    assert eventos_outbox("cadastro.curso.upserted")[-1]["data"]["codigo"] == "ENG"


def test_remover_coordenacao_volta_a_professor(coord):
    from apps.contas.models import User

    r = coord.patch(f"/api/auth/cursos/{coord.curso.id}/", {"coordenador": None}, format="json")
    assert r.status_code == 200
    assert User.objects.get(email="coord@ufvjm.edu.br").papel == "professor"


def test_excluir_aluno_publica_deleted(coord):
    from apps.academico.models import Aluno
    from apps.contas.models import User

    r = coord.post(
        "/api/auth/alunos/",
        {"nome": "A", "matricula": "9", "email": "a9@ufvjm.edu.br", "curso": str(coord.curso.id)},
        format="json",
    )
    assert coord.delete(f"/api/auth/alunos/{r.data['id']}/").status_code == 204
    assert not Aluno.objects.filter(pk=r.data["id"]).exists()
    assert not User.objects.filter(email="a9@ufvjm.edu.br").exists()
    assert eventos_outbox("cadastro.aluno.deleted")[-1]["data"]["id"] == r.data["id"]


def test_excluir_curso_com_alunos_409(coord):
    coord.post(
        "/api/auth/alunos/",
        {"nome": "A", "matricula": "9", "email": "a9@ufvjm.edu.br", "curso": str(coord.curso.id)},
        format="json",
    )
    r = coord.delete(f"/api/auth/cursos/{coord.curso.id}/")
    assert r.status_code == 409 and r.data["codigo"] == "curso_com_alunos"


@pytest.mark.parametrize("papel,esperado", [("aluno", 403), ("professor", 403), ("coordenador", 201), ("admin", 201)])
def test_matriz_criar_curso(ator, papel, esperado):
    r = ator(papel).client.post("/api/auth/cursos/", {"nome": "C", "codigo": f"C{papel[:3]}"}, format="json")
    assert r.status_code == esperado


def test_anonimo_nao_acessa_restritos(api):
    for url in [
        "/api/auth/cursos/",
        "/api/auth/alunos/",
        "/api/auth/professores/",
        "/api/auth/me/",
        "/api/auth/auditoria/",
        "/api/auth/me/dashboard-config/",
    ]:
        assert api.get(url).status_code == 401, url
    assert api.post("/api/auth/cursos/", {"nome": "x", "codigo": "x"}).status_code == 401


def test_visibilidade_de_alunos(coord, criar_usuario, logar):
    from apps.academico.models import Aluno, Professor

    outro = criar_usuario("professor", email="outro@ufvjm.edu.br")
    p2 = Professor.objects.create(user=outro, nome="Outro", email=outro.email, departamento="X")
    ua = criar_usuario("aluno", email="al1@ufvjm.edu.br")
    Aluno.objects.create(
        user=ua, nome="Al1", matricula="m1", email=ua.email, curso=coord.curso, orientador_atual=coord.prof
    )
    ub = criar_usuario("aluno", email="al2@ufvjm.edu.br")
    Aluno.objects.create(user=ub, nome="Al2", matricula="m2", email=ub.email, curso=coord.curso, orientador_atual=p2)
    assert logar("outro@ufvjm.edu.br").get("/api/auth/alunos/").data["count"] == 1
    assert logar("al1@ufvjm.edu.br").get("/api/auth/alunos/").data["count"] == 1
    assert coord.get("/api/auth/alunos/").data["count"] == 2


def test_historico_registra_quem_alterou(coord):
    r = coord.post(
        "/api/auth/professores/", {"nome": "P", "email": "p@ufvjm.edu.br", "departamento": "A"}, format="json"
    )
    pid = r.data["id"]
    coord.patch(f"/api/auth/professores/{pid}/", {"departamento": "B"}, format="json")
    h = coord.get(f"/api/auth/professores/{pid}/historico/").data["historico"]
    assert h[0]["tipo"] == "alteracao"
    assert h[0]["alteracoes"] == [{"campo": "departamento", "anterior": "A", "novo": "B"}]
    from tcc_common.auth.jwt import decodificar_token

    assert h[0]["usuario_id"] == decodificar_token(coord.tokens["access"])["sub"]


def test_auditoria_crud_e_consulta(coord, ator):
    coord.post("/api/auth/cursos/", {"nome": "Novo", "codigo": "NV"}, format="json")
    r = coord.get("/api/auth/auditoria/?acao=criacao")
    assert r.status_code == 200
    assert any(x["recurso"] == "curso" for x in r.data["results"])
    assert ator("aluno").client.get("/api/auth/auditoria/").status_code == 403
    assert ator("professor").client.get("/api/auth/auditoria/").status_code == 403


def test_consumer_audit_registro_centraliza():
    from apps.auditoria.eventos import HANDLERS
    from apps.auditoria.models import RegistroAuditoria
    from tcc_common.events.consumer import encontrar_handler, processar_evento
    from tcc_common.testing import envelope

    env = envelope(
        "audit.registro",
        {
            "usuario_id": None,
            "acao": "upload",
            "recurso": "monografia",
            "recurso_id": "abc",
            "detalhes": {"x": 1},
            "ip": "10.0.0.1",
        },
    )
    env["producer"] = "monografias-service"
    h = encontrar_handler(HANDLERS, "audit.registro")
    assert processar_evento(env, h) == "processado"
    assert processar_evento(env, h) == "duplicado"
    reg = RegistroAuditoria.objects.get(acao="upload")
    assert reg.servico_origem == "monografias-service"
    assert RegistroAuditoria.objects.filter(acao="upload").count() == 1


def test_consumer_integridade_violada_critico():
    from apps.auditoria.eventos import HANDLERS
    from apps.auditoria.models import RegistroAuditoria
    from tcc_common.events.consumer import encontrar_handler, processar_evento
    from tcc_common.testing import envelope

    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "titulo": "t",
        "status": "aprovada",
        "aprovacao_orientador": "aprovada",
        "aluno_id": None,
        "orientador_id": None,
        "curso_id": None,
    }
    env = envelope("monografia.integridade_violada", {**base, "sha_esperado": "a", "sha_atual": "b"})
    processar_evento(env, encontrar_handler(HANDLERS, env["type"]))
    assert RegistroAuditoria.objects.get(acao="integridade_violada").nivel == "critico"


def test_comandos_admin_e_senhas_demo(criar_usuario):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    from apps.contas.models import User

    call_command("garantir_admin", email="root@tcc.local", senha="Admin@Forte#2026")
    adm = User.objects.get(email="root@tcc.local")
    assert adm.papel == "admin" and adm.is_superuser and adm.check_password("Admin@Forte#2026")
    criar_usuario(email="x@demo.tcc.br", senha=None)
    criar_usuario(email="real@ufvjm.edu.br", senha="Outra@Senha#2026")
    with pytest.raises(CommandError):
        call_command("definir_senhas_demo", senha="Demo@Tcc#2026")
    call_command("definir_senhas_demo", senha="Demo@Tcc#2026", confirmar=True)
    assert User.objects.get(email="x@demo.tcc.br").check_password("Demo@Tcc#2026")
    assert not User.objects.get(email="real@ufvjm.edu.br").check_password("Demo@Tcc#2026")


def test_coordenador_gerencia_somente_alunos_do_proprio_curso(coord, ator):
    outro = coord.post("/api/auth/cursos/", {"nome": "Outro curso", "codigo": "OUT"}, format="json").data
    r = coord.post(
        "/api/auth/alunos/",
        {"nome": "X", "matricula": "x1", "email": "x1@ufvjm.edu.br", "curso": outro["id"]},
        format="json",
    )
    assert r.status_code == 403
    r = coord.post(
        "/api/auth/alunos/",
        {"nome": "Y", "matricula": "y1", "email": "y1@ufvjm.edu.br", "curso": str(coord.curso.id)},
        format="json",
    )
    assert r.status_code == 201
    assert coord.patch(f"/api/auth/alunos/{r.data['id']}/", {"curso": outro["id"]}, format="json").status_code == 403
    assert coord.patch(f"/api/auth/alunos/{r.data['id']}/", {"nome": "Y2"}, format="json").status_code == 200
    assert (
        ator("admin")
        .client.patch(f"/api/auth/alunos/{r.data['id']}/", {"curso": outro["id"]}, format="json")
        .status_code
        == 200
    )

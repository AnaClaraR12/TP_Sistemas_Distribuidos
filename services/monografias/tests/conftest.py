import os
import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile


def bytes_pdf(conteudo: str = "", tamanho: int = 0) -> bytes:
    corpo = f"%PDF-1.4\n% {conteudo or uuid.uuid4().hex}\n".encode()
    if tamanho > len(corpo):
        corpo += os.urandom(tamanho - len(corpo) - 6) + b"\n%%EOF"
    else:
        corpo += b"%%EOF\n"
    return corpo


def arquivo_pdf(nome="tcc.pdf", conteudo="", tamanho=0, content_type="application/pdf"):
    return SimpleUploadedFile(nome, bytes_pdf(conteudo, tamanho), content_type=content_type)


@pytest.fixture
def cenario(db, ator):
    """Curso, orientador, coordenador, aluno (read models) e clientes autenticados."""
    from apps.monografias.models import AlunoRef, CursoRef, ProfessorRef

    curso = CursoRef.objects.create(id=uuid.uuid4(), nome="Sistemas de Informação", codigo="SI")
    orientador = ProfessorRef.objects.create(id=uuid.uuid4(), nome="Prof. Orientador", email="ori@ufvjm.edu.br")
    outro_prof = ProfessorRef.objects.create(id=uuid.uuid4(), nome="Prof. Outro", email="outro@ufvjm.edu.br")
    coord = ProfessorRef.objects.create(id=uuid.uuid4(), nome="Coord", email="coord@ufvjm.edu.br")
    CursoRef.objects.filter(pk=curso.pk).update(coordenador_id=coord.id)
    aluno = AlunoRef.objects.create(
        id=uuid.uuid4(),
        nome="Ana Aluna",
        email="ana@ufvjm.edu.br",
        matricula="1",
        curso_id=curso.id,
        orientador_id=orientador.id,
    )
    outro_aluno = AlunoRef.objects.create(
        id=uuid.uuid4(),
        nome="Beto",
        email="beto@ufvjm.edu.br",
        matricula="2",
        curso_id=curso.id,
        orientador_id=orientador.id,
    )

    class C:
        pass

    c = C()
    c.curso, c.orientador_ref, c.aluno_ref = curso, orientador, aluno
    c.aluno = ator("aluno", aluno_id=str(aluno.id), curso_ids=[curso.id])
    c.outro_aluno = ator("aluno", aluno_id=str(outro_aluno.id), curso_ids=[curso.id])
    c.orientador = ator("professor", professor_id=str(orientador.id))
    c.outro_prof = ator("professor", professor_id=str(outro_prof.id))
    c.coord = ator("coordenador", professor_id=str(coord.id), curso_ids=[curso.id])
    c.admin = ator("admin")
    return c


@pytest.fixture
def criar_rascunho(cenario):
    def _criar(cliente=None, **kw):
        cliente = cliente or cenario.aluno.client
        payload = {
            "titulo": kw.get("titulo", "Sistemas distribuídos com microsserviços"),
            "resumo": kw.get("resumo", "Estudo sobre filas de eventos, cache Redis e escalabilidade."),
            "palavras_chave": kw.get("palavras_chave", ["sistemas distribuídos", "redis", "rabbitmq"]),
            "orientador_id": str(kw.get("orientador_id", cenario.orientador_ref.id)),
        }
        r = cliente.post("/api/monografias", payload, format="json")
        assert r.status_code == 201, r.data
        return r.data["id"]

    return _criar


@pytest.fixture
def submetida(cenario, criar_rascunho):
    """Monografia em avaliação (upload + submeter) com o lock já liberado pela extração."""
    from tcc_common.cache.redis import get_redis

    mid = criar_rascunho()
    r = cenario.aluno.client.post(f"/api/monografias/{mid}/arquivo/", {"arquivo": arquivo_pdf()}, format="multipart")
    assert r.status_code == 201, r.data
    r = cenario.aluno.client.post(f"/api/monografias/{mid}/submeter/")
    assert r.status_code == 202, r.data
    get_redis().delete(f"upload_em_andamento:{mid}")
    return mid


@pytest.fixture
def aprovada_orientador(cenario, submetida):
    r = cenario.orientador.client.post(f"/api/monografias/{submetida}/aprovar-orientador/")
    assert r.status_code == 200, r.data
    return submetida

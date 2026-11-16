import hashlib
import io
import uuid

import pytest


def pdf_com_texto(paginas: list[str]) -> bytes:
    """Gera um PDF real com texto (reportlab)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for texto in paginas:
        y = 800
        for linha in texto.split("\n"):
            c.drawString(50, y, linha)
            y -= 16
        c.showPage()
    c.save()
    return buf.getvalue()


def pdf_sem_texto() -> bytes:
    """PDF válido só com desenho (simula PDF escaneado sem camada de texto)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.rect(100, 100, 300, 300, fill=1)
    c.showPage()
    c.save()
    return buf.getvalue()


def dados_mono(mid=None, **kw):
    return {
        "id": str(mid or uuid.uuid4()),
        "titulo": kw.get("titulo", "Sistemas distribuídos e microsserviços"),
        "status": kw.get("status", "em_avaliacao"),
        "aprovacao_orientador": "pendente",
        "aluno_id": str(uuid.uuid4()),
        "orientador_id": str(kw.get("orientador_id", uuid.uuid4())),
        "curso_id": str(kw.get("curso_id", uuid.uuid4())),
        "sha256": "0" * 64,
        "submetida_em": "2026-05-10T14:03:11Z",
    }


def dados_publicada(base: dict, sha: str, **kw):
    return {
        **base,
        "status": "publicada",
        "resumo": kw.get("resumo", "Estudo sobre filas de eventos e cache distribuído."),
        "palavras_chave": kw.get("palavras_chave", ["sistemas distribuídos", "redis", "rabbitmq"]),
        "autor_nome": kw.get("autor_nome", "Ana Júlia Souza"),
        "orientador_nome": kw.get("orientador_nome", "Prof. João Pereira"),
        "curso_nome": kw.get("curso_nome", "Sistemas de Informação"),
        "ano_defesa": kw.get("ano_defesa", 2026),
        "sha256": sha,
        "publicada_em": "2026-07-01T12:00:00Z",
    }


@pytest.fixture
def processar(django_capture_on_commit_callbacks):
    """Processa um evento como o consumer real, executando os callbacks pós-commit."""
    from apps.indexacao.eventos import HANDLERS
    from tcc_common.events.consumer import processar_evento
    from tcc_common.testing import encontrar_handler, envelope

    def _processar(tipo, data):
        env = envelope(tipo, data)
        with django_capture_on_commit_callbacks(execute=True):
            return processar_evento(env, encontrar_handler(HANDLERS, tipo))

    return _processar


@pytest.fixture
def mock_pdf():
    """Registra respostas do endpoint interno do monografias-service."""
    import responses

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:

        def _registrar(mid, conteudo: bytes, status=200):
            rsps.get(
                f"http://monografias-service:8002/internal/monografias/{mid}/arquivo/", body=conteudo, status=status
            )

        yield _registrar


CORPO = "Capitulo 1\nA arquitetura usa um balanceador quiescente para orquestrar replicas.\nConclusao final."


@pytest.fixture
def publicar(processar, mock_pdf):
    def _publicar(paginas=None, **kw):
        base = dados_mono(**{k: v for k, v in kw.items() if k in ("titulo", "orientador_id", "curso_id")})
        conteudo = pdf_com_texto(paginas or [CORPO])
        mock_pdf(base["id"], conteudo)
        assert processar("monografia.submetida", base) == "processado"
        sha = hashlib.sha256(conteudo).hexdigest()
        extras = {k: v for k, v in kw.items() if k not in ("titulo", "orientador_id", "curso_id")}
        assert processar("monografia.publicada", dados_publicada(base, sha, **extras)) == "processado"
        return base["id"]

    return _publicar

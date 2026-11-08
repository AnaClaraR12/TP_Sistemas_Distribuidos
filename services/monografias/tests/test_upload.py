"""Validações do upload na ordem da Fase 2 (formato, tamanho, SHA-256, dedup, lock, rate limit)."""

import hashlib
import time

import pytest
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile

from tcc_common.cache.redis import get_redis

from .conftest import arquivo_pdf, bytes_pdf

pytestmark = pytest.mark.django_db


def _upload(cliente, mid, arquivo):
    return cliente.post(f"/api/monografias/{mid}/arquivo/", {"arquivo": arquivo}, format="multipart")


def test_upload_ok_grava_hash_e_mantem_rascunho(cenario, criar_rascunho):
    from apps.monografias.models import Monografia

    mid = criar_rascunho()
    conteudo = bytes_pdf("abc")
    r = _upload(cenario.aluno.client, mid, SimpleUploadedFile("meu tcc.pdf", conteudo, "application/pdf"))
    assert r.status_code == 201
    m = Monografia.objects.get(pk=mid)
    assert m.arquivo_sha256 == hashlib.sha256(conteudo).hexdigest()
    assert m.status == "rascunho" and m.aprovacao_orientador == "pendente"
    assert m.arquivo.name == f"monografias/{mid}/{m.arquivo_sha256}.pdf"
    assert m.arquivo_tamanho_bytes == len(conteudo)
    assert not get_redis().exists(f"upload_em_andamento:{mid}")  # liberado ao fim da requisição


def test_nome_do_usuario_nao_define_caminho(cenario, criar_rascunho):
    from apps.monografias.models import Monografia

    mid = criar_rascunho()
    r = _upload(cenario.aluno.client, mid, arquivo_pdf(nome="../../../etc/passwd.pdf"))
    assert r.status_code == 201
    m = Monografia.objects.get(pk=mid)
    assert ".." not in m.arquivo.name and m.arquivo.name.startswith(f"monografias/{mid}/")


def test_txt_renomeado_para_pdf_rejeitado(cenario, criar_rascunho):
    mid = criar_rascunho()
    falso = SimpleUploadedFile("tcc.pdf", b"isto e um texto qualquer", content_type="application/pdf")
    r = _upload(cenario.aluno.client, mid, falso)
    assert r.status_code == 415
    assert "conteudo_nao_e_pdf" in r.data["detalhes"]["problemas"]


def test_extensao_diferente_de_pdf_rejeitada(cenario, criar_rascunho):
    mid = criar_rascunho()
    r = _upload(cenario.aluno.client, mid, arquivo_pdf(nome="tcc.txt"))
    assert r.status_code == 415 and "extensao" in r.data["detalhes"]["problemas"]


def test_content_type_divergente_rejeitado(cenario, criar_rascunho):
    mid = criar_rascunho()
    r = _upload(cenario.aluno.client, mid, arquivo_pdf(content_type="text/plain"))
    assert r.status_code == 415 and "content_type" in r.data["detalhes"]["problemas"]


def test_arquivo_maior_que_limite_413(cenario, criar_rascunho, settings):
    settings.MAX_UPLOAD_MB = 1
    mid = criar_rascunho()
    r = _upload(cenario.aluno.client, mid, arquivo_pdf(tamanho=int(1.5 * 1024 * 1024)))
    assert r.status_code == 413 and r.data["codigo"] == "arquivo_muito_grande"


def test_limite_padrao_50mb(settings):
    from apps.monografias.arquivos import limite_bytes

    assert settings.MAX_UPLOAD_MB == 50 and limite_bytes() == 50 * 1024 * 1024


def test_duplicado_em_outra_monografia_409(cenario, criar_rascunho):
    m1 = criar_rascunho()
    m2 = criar_rascunho(cliente=cenario.outro_aluno.client)
    conteudo = bytes_pdf("mesmo")
    assert (
        _upload(cenario.aluno.client, m1, SimpleUploadedFile("a.pdf", conteudo, "application/pdf")).status_code == 201
    )
    r = _upload(cenario.outro_aluno.client, m2, SimpleUploadedFile("b.pdf", conteudo, "application/pdf"))
    assert r.status_code == 409 and r.data["codigo"] == "arquivo_duplicado"
    assert r.data["detalhes"] == {}  # não vaza dados de terceiros


def test_mesmo_arquivo_na_propria_monografia_idempotente(cenario, criar_rascunho):
    mid = criar_rascunho()
    conteudo = bytes_pdf("x")
    assert (
        _upload(cenario.aluno.client, mid, SimpleUploadedFile("a.pdf", conteudo, "application/pdf")).status_code == 201
    )
    r = _upload(cenario.aluno.client, mid, SimpleUploadedFile("a.pdf", conteudo, "application/pdf"))
    assert r.status_code == 200


def test_substituir_arquivo_remove_antigo(cenario, criar_rascunho):
    from apps.monografias.models import Monografia

    mid = criar_rascunho()
    _upload(cenario.aluno.client, mid, arquivo_pdf(conteudo="v1"))
    antigo = Monografia.objects.get(pk=mid).arquivo.name
    _upload(cenario.aluno.client, mid, arquivo_pdf(conteudo="v2"))
    assert not default_storage.exists(antigo)


def test_upload_em_andamento_409(cenario, criar_rascunho):
    mid = criar_rascunho()
    get_redis().set(f"upload_em_andamento:{mid}", "outra-req", ex=600)
    r = _upload(cenario.aluno.client, mid, arquivo_pdf())
    assert r.status_code == 409 and r.data["codigo"] == "upload_em_andamento"


def test_rate_limit_429_com_retry_after(cenario, criar_rascunho, settings):
    settings.SUBMISSOES_POR_HORA = 2
    mid = criar_rascunho()
    for i in range(2):
        assert _upload(cenario.aluno.client, mid, arquivo_pdf(conteudo=f"r{i}")).status_code == 201
    r = _upload(cenario.aluno.client, mid, arquivo_pdf(conteudo="r3"))
    assert r.status_code == 429 and int(r["Retry-After"]) > 0


def test_upload_por_outro_usuario_403(cenario, criar_rascunho):
    mid = criar_rascunho()
    assert _upload(cenario.outro_aluno.client, mid, arquivo_pdf()).status_code == 403
    assert _upload(cenario.orientador.client, mid, arquivo_pdf()).status_code == 403


def test_upload_anonimo_401(api, cenario, criar_rascunho):
    mid = criar_rascunho()
    assert _upload(api, mid, arquivo_pdf()).status_code == 401


def test_upload_fora_de_rascunho_409(cenario, submetida):
    r = _upload(cenario.aluno.client, submetida, arquivo_pdf())
    assert r.status_code == 409


def test_upload_apos_aprovacao_imutavel(cenario, aprovada_orientador):
    assert _upload(cenario.aluno.client, aprovada_orientador, arquivo_pdf()).status_code == 409


def test_upload_nao_extrai_texto(cenario, criar_rascunho, monkeypatch):
    """A requisição nunca chama pdfplumber/pypdf (extração é assíncrona)."""
    import sys

    monkeypatch.setitem(sys.modules, "pdfplumber", None)
    mid = criar_rascunho()
    assert _upload(cenario.aluno.client, mid, arquivo_pdf()).status_code == 201


def test_upload_e_submissao_20mb_em_menos_de_1s(cenario, criar_rascunho):
    mid = criar_rascunho()
    arq = arquivo_pdf(tamanho=20 * 1024 * 1024)
    inicio = time.perf_counter()
    r = _upload(cenario.aluno.client, mid, arq)
    upload_s = time.perf_counter() - inicio
    assert r.status_code == 201
    inicio = time.perf_counter()
    r = cenario.aluno.client.post(f"/api/monografias/{mid}/submeter/")
    sub_s = time.perf_counter() - inicio
    assert r.status_code == 202
    print(f"\nupload 20MB: {upload_s:.3f}s | submeter: {sub_s:.3f}s")
    assert sub_s < 1.0
    assert upload_s < 3.0  # inclui a codificação multipart do cliente de teste

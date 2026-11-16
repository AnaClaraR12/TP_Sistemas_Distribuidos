"""Extração assíncrona, indexação FTS, busca pública, cache Redis e endpoints públicos."""

import hashlib
import time
import uuid

import pytest

from tcc_common.cache.redis import get_redis
from tcc_common.testing import eventos_outbox

from .conftest import dados_mono, dados_publicada, pdf_com_texto, pdf_sem_texto

pytestmark = pytest.mark.django_db


def test_extracao_assincrona_indexa_sem_publicar(processar, mock_pdf, api):
    from apps.indexacao.models import DocumentoIndexado

    base = dados_mono()
    mock_pdf(base["id"], pdf_com_texto(["Pagina um sobre filas", "Pagina dois sobre cache"]))
    processar("monografia.submetida", base)
    doc = DocumentoIndexado.objects.get(pk=base["id"])
    assert "filas" in doc.texto_completo and doc.paginas == 2 and doc.sem_texto is False
    assert doc.publico is False and doc.search_vector
    ev = eventos_outbox("monografia.texto_extraido")[-1]["data"]
    assert ev == {**ev, "id": base["id"], "paginas": 2, "sem_texto": False}
    # antes da publicação NÃO aparece na busca pública
    r = api.get("/api/repositorio/monografias/?busca=filas")
    assert r.status_code == 200 and r.data["count"] == 0
    assert api.get(f"/api/repositorio/monografias/{base['id']}/").status_code == 404


def test_pdf_sem_texto_nao_e_erro(processar, mock_pdf):
    from apps.indexacao.models import DocumentoIndexado

    base = dados_mono()
    mock_pdf(base["id"], pdf_sem_texto())
    processar("monografia.submetida", base)
    doc = DocumentoIndexado.objects.get(pk=base["id"])
    assert doc.sem_texto is True and doc.texto_completo == ""
    assert eventos_outbox("monografia.texto_extraido")[-1]["data"]["sem_texto"] is True


def test_pdf_corrompido_publica_extracao_falhou(processar, mock_pdf):
    base = dados_mono()
    mock_pdf(base["id"], b"%PDF-1.4\nlixo binario sem estrutura \x00\x01\x02")
    assert processar("monografia.submetida", base) == "processado"
    ev = eventos_outbox("monografia.extracao_falhou")[-1]["data"]
    assert ev["id"] == base["id"] and ev["motivo"]
    assert not eventos_outbox("monografia.texto_extraido")


def test_download_indisponivel_gera_retry_e_falha_definitiva(processar, mock_pdf):
    from apps.indexacao.eventos import on_submetida
    from apps.indexacao.extracao import DownloadFalhou
    from tcc_common.testing import envelope

    base = dados_mono()
    mock_pdf(base["id"], b"", status=503)
    with pytest.raises(DownloadFalhou):
        processar("monografia.submetida", base)  # consumer => nack/retry
    on_submetida.falha_definitiva(
        envelope("monografia.submetida", {**base, "sha256": "x", "submetida_em": "x"}), DownloadFalhou("x")
    )
    assert eventos_outbox("monografia.extracao_falhou")[-1]["data"]["id"] == base["id"]


def test_idempotencia_da_extracao(processar, mock_pdf):
    from apps.indexacao.eventos import HANDLERS
    from tcc_common.events.consumer import processar_evento
    from tcc_common.testing import encontrar_handler, envelope

    base = dados_mono()
    mock_pdf(base["id"], pdf_com_texto(["texto"]))
    env = envelope("monografia.submetida", base)
    h = encontrar_handler(HANDLERS, env["type"])
    assert processar_evento(env, h) == "processado"
    assert processar_evento(env, h) == "duplicado"
    assert len(eventos_outbox("monografia.texto_extraido")) == 1


def test_publicacao_torna_publico_e_invalida_cache(publicar, api):
    get_redis().set("busca:versao", 5)
    mid = publicar()
    assert get_redis().get("busca:versao") == "6"
    r = api.get("/api/repositorio/monografias/")
    assert r.data["count"] == 1 and r.data["results"][0]["id"] == mid
    assert r.data["results"][0]["autor_nome"] == "Ana Júlia Souza"
    assert eventos_outbox("repositorio.indexado")


def test_busca_por_palavra_apenas_no_corpo_do_pdf(publicar, api):
    mid = publicar()
    r = api.get("/api/repositorio/monografias/?busca=quiescente")
    assert r.data["count"] == 1 and r.data["results"][0]["id"] == mid


def test_busca_insensivel_a_acentos(publicar, api):
    publicar(titulo="Avaliação de monografía em sistemas distribuídos")
    for termo in ("monografia", "monografía", "AVALIACAO", "distribuidos", "sistemas distribuidos"):
        assert api.get("/api/repositorio/monografias/", {"busca": termo}).data["count"] == 1, termo


def test_ranking_titulo_pesa_mais_que_corpo(publicar, api):
    no_titulo = publicar(titulo="Kubernetes na prática", paginas=["texto qualquer"])
    no_corpo = publicar(titulo="Outro assunto", paginas=["menciona kubernetes uma vez"])
    r = api.get("/api/repositorio/monografias/?busca=kubernetes&ordenar=relevancia")
    ids = [x["id"] for x in r.data["results"]]
    assert ids == [no_titulo, no_corpo]
    assert r.data["results"][0]["relevancia"] > r.data["results"][1]["relevancia"]


def test_trecho_destacado(publicar, api):
    publicar(resumo="Este trabalho estuda filas de eventos com RabbitMQ em larga escala.")
    r = api.get("/api/repositorio/monografias/?busca=rabbitmq")
    assert "[[" in r.data["results"][0]["trecho"]


@pytest.mark.parametrize(
    "filtro,valor,esperado",
    [
        ("titulo", "microsservicos", 1),
        ("titulo", "inexistente", 0),
        ("autor", "ana julia", 1),
        ("autor", "carlos", 0),
        ("orientador", "joão", 1),
        ("ano_defesa", "2026", 1),
        ("ano_defesa", "2020", 0),
        ("curso", "informação", 1),
        ("palavras_chave", "redis,outra", 1),
        ("palavras_chave", "java", 0),
    ],
)
def test_filtros(publicar, api, filtro, valor, esperado):
    publicar()
    assert api.get("/api/repositorio/monografias/", {filtro: valor}).data["count"] == esperado


def test_filtro_por_uuid_de_orientador_e_curso(publicar, api):
    oid, cid = uuid.uuid4(), uuid.uuid4()
    publicar(orientador_id=oid, curso_id=cid)
    publicar()
    assert api.get(f"/api/repositorio/monografias/?orientador={oid}").data["count"] == 1
    assert api.get(f"/api/repositorio/monografias/?curso={cid}").data["count"] == 1


def test_cache_hit_miss_e_normalizacao(publicar, api):
    publicar()
    r1 = api.get("/api/repositorio/monografias/?busca=Redis&ano_defesa=2026")
    assert r1["X-Cache"] == "MISS"
    r2 = api.get("/api/repositorio/monografias/?ano_defesa=2026&busca=redis%20%20")
    assert r2["X-Cache"] == "HIT" and r2.data == r1.data
    chaves = [k for k in get_redis().keys("busca:*") if k != "busca:versao"]
    assert len(chaves) == 1 and chaves[0].startswith("busca:1:")  # versão 1 após a publicação


def test_hit_e_mais_rapido_que_miss(publicar, api):
    for i in range(15):
        publicar(titulo=f"Trabalho {i} sobre redes")
    t0 = time.perf_counter()
    assert api.get("/api/repositorio/monografias/?busca=redes")["X-Cache"] == "MISS"
    miss = time.perf_counter() - t0
    t0 = time.perf_counter()
    assert api.get("/api/repositorio/monografias/?busca=redes")["X-Cache"] == "HIT"
    hit = time.perf_counter() - t0
    print(f"\nMISS {miss*1000:.1f} ms | HIT {hit*1000:.1f} ms")
    assert hit < miss


def test_cache_invalidado_apos_nova_publicacao(publicar, api):
    publicar(titulo="Primeiro sobre grafos")
    assert api.get("/api/repositorio/monografias/?busca=grafos").data["count"] == 1
    publicar(titulo="Segundo sobre grafos")
    r = api.get("/api/repositorio/monografias/?busca=grafos")
    assert r["X-Cache"] == "MISS" and r.data["count"] == 2


def test_stampede_quem_perde_o_lock_espera(publicar, api):
    from apps.indexacao import cache as modcache

    publicar()
    chave, h = modcache.chave_busca(api.get("/x").wsgi_request.GET)
    get_redis().set(f"busca_lock:{h}", "1", ex=5)  # outro worker está calculando
    get_redis().set(chave, '{"count": 99, "results": []}', ex=300)
    dados, status = modcache.obter_ou_calcular(api.get("/x").wsgi_request.GET, lambda: {"count": -1})
    assert status == "HIT" and dados["count"] == 99


def test_headers_http_cache_e_etag(publicar, api):
    publicar()
    r = api.get("/api/repositorio/monografias/")
    assert r["Cache-Control"] == "public, max-age=60" and r.has_header("ETag")
    r304 = api.get("/api/repositorio/monografias/", HTTP_IF_NONE_MATCH=r["ETag"])
    assert r304.status_code == 304


def test_detalhe_e_download_com_hash(publicar, api):
    mid = publicar()
    r = api.get(f"/api/repositorio/monografias/{mid}/")
    assert r.status_code == 200 and r.data["downloads"] == 0
    d = api.get(f"/api/repositorio/monografias/{mid}/download/")
    conteudo = b"".join(d.streaming_content)
    assert d.status_code == 200 and conteudo.startswith(b"%PDF")
    assert hashlib.sha256(conteudo).hexdigest() == d["X-Arquivo-SHA256"]
    assert get_redis().get(f"downloads:{mid}") == "1"


def test_publico_sem_autenticacao_e_token_invalido_ignorado(publicar, api):
    publicar()
    assert api.get("/api/repositorio/monografias/", HTTP_AUTHORIZATION="Bearer lixo").status_code == 200
    assert api.post("/api/repositorio/monografias/", {}).status_code in (403, 405)
    assert api.delete(f"/api/repositorio/monografias/{uuid.uuid4()}/").status_code in (403, 405)


def test_endpoints_publicos_cursos_e_orientadores(processar, publicar, api):
    cid, pid = str(uuid.uuid4()), str(uuid.uuid4())
    processar("cadastro.curso.upserted", {"id": cid, "nome": "Engenharia", "codigo": "ENG", "coordenador_id": None})
    processar(
        "cadastro.professor.upserted", {"id": pid, "nome": "Profa. Maria", "email": "m@x.br", "departamento": "DECOM"}
    )
    publicar(curso_id=cid, orientador_id=pid)
    cursos = api.get("/api/repositorio/cursos/").json()
    assert cursos == [{"id": cid, "nome": "Engenharia", "codigo": "ENG", "total_publicadas": 1}]
    orient = api.get("/api/repositorio/orientadores/").json()
    assert orient[0]["nome"] == "Profa. Maria" and orient[0]["total_publicadas"] == 1
    assert "email" not in orient[0]  # dado pessoal não exposto publicamente


def test_throttling_anonimo(publicar, api, settings):
    from rest_framework.settings import api_settings
    from rest_framework.throttling import AnonRateThrottle

    rates = {**api_settings.DEFAULT_THROTTLE_RATES, "anon": "3/min"}
    AnonRateThrottle.THROTTLE_RATES = rates
    try:
        codigos = [api.get("/api/repositorio/orientadores/").status_code for _ in range(4)]
    finally:
        AnonRateThrottle.THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES
    assert codigos[-1] == 429


def test_versao_corrigida_reextrai_na_publicacao(processar, mock_pdf, api):
    from apps.indexacao.models import DocumentoIndexado

    base = dados_mono()
    mock_pdf(base["id"], pdf_com_texto(["versao original"]))
    processar("monografia.submetida", base)
    # publicação com a versão corrigida (hash diferente) — mesmo endpoint retorna o novo arquivo
    import responses

    novo = pdf_com_texto(["versao corrigida com termo zygomorfo"])
    with responses.RequestsMock() as rsps:
        rsps.get(f"http://monografias-service:8002/internal/monografias/{base['id']}/arquivo/", body=novo)
        processar("monografia.publicada", dados_publicada(base, hashlib.sha256(novo).hexdigest()))
    assert "zygomorfo" in DocumentoIndexado.objects.get(pk=base["id"]).texto_completo
    assert api.get("/api/repositorio/monografias/?busca=zygomorfo").data["count"] == 1


def test_busca_usa_indice_gin_explain(publicar):
    """Com volume suficiente o planner escolhe o GIN; aqui conferimos que o índice existe."""
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT indexdef FROM pg_indexes WHERE indexname = 'doc_search_vector_gin'")
        assert "gin" in cur.fetchone()[0].lower()


def test_cache_so_invalida_apos_commit(processar, mock_pdf, django_capture_on_commit_callbacks):
    """Sem isso, uma busca concorrente gravaria o resultado antigo na versão nova do cache."""
    import hashlib

    from apps.indexacao.eventos import HANDLERS
    from tcc_common.events.consumer import processar_evento
    from tcc_common.testing import encontrar_handler, envelope

    base = dados_mono()
    conteudo = pdf_com_texto(["corpo"])
    mock_pdf(base["id"], conteudo)
    processar("monografia.submetida", base)
    get_redis().set("busca:versao", 10)
    env = envelope("monografia.publicada", dados_publicada(base, hashlib.sha256(conteudo).hexdigest()))
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        processar_evento(env, encontrar_handler(HANDLERS, env["type"]))
        assert get_redis().get("busca:versao") == "10"  # ainda não commitou: cache intacto
    for cb in callbacks:
        cb()
    assert get_redis().get("busca:versao") == "11"

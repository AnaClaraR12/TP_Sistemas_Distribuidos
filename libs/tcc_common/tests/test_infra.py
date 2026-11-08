"""Exception handler, healthchecks, rate limit, locks, middleware e permissões."""

import pytest

from tcc_common.cache.redis import adquirir_lock, get_redis, liberar_lock, verificar_rate_limit
from tcc_common.texto import normalizar

pytestmark = pytest.mark.django_db


def test_erro_negocio_formato_padrao(api):
    r = api.get("/erro/")
    assert r.status_code == 409
    assert r.json() == {"codigo": "regra_x", "mensagem": "Regra violada.", "detalhes": {"a": 1}}


def test_validacao_formato_padrao(api):
    r = api.post("/erro/", {}, format="json")
    assert r.status_code == 400
    assert r.json()["codigo"] == "requisicao_invalida" and "nome" in r.json()["detalhes"]


def test_health_e_ready(api):
    assert api.get("/health/").json()["status"] == "ok"
    r = api.get("/ready/")
    assert r.status_code == 200 and r.json()["dependencias"]["postgres"] == "ok"
    assert r.json()["dependencias"]["redis"] == "ok"


def test_request_id_propagado(api):
    r = api.get("/health/", HTTP_X_REQUEST_ID="abc12345-req")
    assert r["X-Request-ID"] == "abc12345-req"
    assert len(api.get("/health/")["X-Request-ID"]) == 32


def test_rate_limit():
    for _ in range(3):
        assert verificar_rate_limit("rl:x", 3, 60) == (True, 0)
    permitido, retry = verificar_rate_limit("rl:x", 3, 60)
    assert permitido is False and 0 < retry <= 60


def test_lock_nx():
    assert adquirir_lock("upload_em_andamento:1", "a", 600) is True
    assert adquirir_lock("upload_em_andamento:1", "b", 600) is False
    liberar_lock("upload_em_andamento:1", "b")  # não é o dono
    assert get_redis().get("upload_em_andamento:1") == "a"
    liberar_lock("upload_em_andamento:1", "a")
    assert not get_redis().exists("upload_em_andamento:1")


def test_token_de_servico(api, servico_client):
    assert api.get("/interno/").status_code == 403
    assert servico_client.get("/interno/").status_code == 200


def test_jwt_validado_localmente(ator):
    from tcc_common.auth.jwt import decodificar_token

    a = ator("professor")
    claims = decodificar_token(a.token)
    assert claims["papel"] == "professor" and claims["professor_id"] == a.professor_id


def test_redis_fora_falha_fechada(settings, monkeypatch, ator):
    from tcc_common.auth import jwt as modjwt

    class Quebrado:
        def exists(self, *_):
            raise ConnectionError

    monkeypatch.setattr(modjwt, "get_redis", lambda: Quebrado())
    assert modjwt.token_revogado("x") is True
    settings.JWT_REVOGACAO_FAIL_OPEN = True
    assert modjwt.token_revogado("x") is False


def test_normalizar():
    assert normalizar("  Monografía   SISTEMAS Distribuídos ") == "monografia sistemas distribuidos"


def test_log_json_mascara_campos_sensiveis():
    import json
    import logging

    from tcc_common.api.logging import JsonFormatter

    rec = logging.makeLogRecord({"msg": "evento", "token": "segredo", "event_id": "e1"})
    saida = json.loads(JsonFormatter("x").format(rec))
    assert saida["token"] == "***" and saida["event_id"] == "e1" and saida["servico"] == "x"

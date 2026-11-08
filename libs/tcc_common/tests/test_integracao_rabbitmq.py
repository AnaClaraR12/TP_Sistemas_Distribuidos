"""Testes de integração com RabbitMQ REAL (rodam no Docker: ``make test-integracao``).

Critérios da Fase 3: durabilidade (consumer fora, 10 eventos, consumer volta),
idempotência por event_id e mensagem veneno na DLQ após as tentativas.
"""

from __future__ import annotations

import json
import os
import time
import uuid

import pytest

pika = pytest.importorskip("pika")

RABBIT = os.environ.get("RABBITMQ_URL_TESTE")
pytestmark = [
    pytest.mark.integracao,
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(not RABBIT, reason="defina RABBITMQ_URL_TESTE para rodar contra um RabbitMQ real"),
]


@pytest.fixture
def rabbit_settings(settings):
    settings.RABBITMQ_URL = RABBIT
    return settings


def _servico():
    return f"teste{uuid.uuid4().hex[:6]}"


def _drenar(consumer, canal, fila, limite_s=5.0):
    fim = time.time() + limite_s
    while time.time() < fim:
        method, props, body = canal.basic_get(fila, auto_ack=False)
        if method is None:
            time.sleep(0.1)
            continue
        consumer._on_message(canal, method, props, body, binding="repositorio.indexado")


def test_durabilidade_10_eventos_com_consumer_fora(rabbit_settings):
    from tcc_common.events.consumer import BaseConsumer
    from tcc_common.events.models import EventoProcessado
    from tcc_common.events.outbox import criar_envelope
    from tcc_common.events.rabbit import Publisher, abrir_conexao

    servico = _servico()
    recebidos = []
    consumer = BaseConsumer(servico, {"repositorio.indexado": lambda e: recebidos.append(e["event_id"])})
    conn = abrir_conexao()
    canal = conn.channel()
    consumer.declarar(canal)  # filas existem, mas ninguém consome
    pub = Publisher()
    envs = [criar_envelope("repositorio.indexado", {"monografia_id": str(i)}) for i in range(10)]
    for e in envs:
        pub.publicar(e)
    pub.fechar()
    _drenar(consumer, canal, consumer.filas["repositorio.indexado"].principal)  # "consumer volta"
    assert sorted(recebidos) == sorted(e["event_id"] for e in envs)
    assert EventoProcessado.objects.count() == 10
    conn.close()


def test_mesmo_event_id_nao_duplica(rabbit_settings):
    from tcc_common.events.consumer import BaseConsumer
    from tcc_common.events.outbox import criar_envelope
    from tcc_common.events.rabbit import Publisher, abrir_conexao

    recebidos = []
    consumer = BaseConsumer(_servico(), {"repositorio.indexado": lambda e: recebidos.append(1)})
    conn = abrir_conexao()
    canal = conn.channel()
    consumer.declarar(canal)
    env = criar_envelope("repositorio.indexado", {"monografia_id": "x"})
    pub = Publisher()
    pub.publicar(env)
    pub.publicar(env)
    pub.fechar()
    _drenar(consumer, canal, consumer.filas["repositorio.indexado"].principal)
    assert len(recebidos) == 1
    conn.close()


def test_veneno_vai_para_dlq(rabbit_settings, monkeypatch):
    from tcc_common.events import rabbit
    from tcc_common.events.consumer import BaseConsumer
    from tcc_common.events.outbox import criar_envelope
    from tcc_common.events.rabbit import Publisher, abrir_conexao

    def quebra(e):
        raise RuntimeError("veneno")

    servico = _servico()
    consumer = BaseConsumer(servico, {"repositorio.indexado": quebra})
    conn = abrir_conexao()
    canal = conn.channel()
    # TTLs curtos para o teste
    consumer.filas["repositorio.indexado"] = rabbit.declarar_fila_consumer(
        canal, servico, "repositorio.indexado", (200, 200, 200)
    )
    pub = Publisher()
    pub.publicar(criar_envelope("repositorio.indexado", {"monografia_id": "v"}))
    pub.fechar()
    filas = consumer.filas["repositorio.indexado"]
    _drenar(consumer, canal, filas.principal, limite_s=4)
    method, props, body = canal.basic_get(filas.dlq, auto_ack=True)
    assert method is not None and json.loads(body)["data"]["monografia_id"] == "v"
    conn.close()

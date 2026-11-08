"""Biblioteca de eventos: envelope, outbox, publisher, consumer (idempotência, retry, DLQ)."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from tcc_common.events import rabbit
from tcc_common.events.consumer import BaseConsumer, casar_routing_key, processar_evento
from tcc_common.events.models import EventoProcessado, OutboxEvento
from tcc_common.events.outbox import criar_envelope, registrar_evento
from tcc_common.events.schemas import EventoInvalido

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "padrao,chave,esperado",
    [
        ("cadastro.#", "cadastro.aluno.upserted", True),
        ("cadastro.#", "cadastro", True),
        ("cadastro.*.deleted", "cadastro.aluno.deleted", True),
        ("cadastro.*.deleted", "cadastro.aluno.upserted", False),
        ("monografia.submetida", "monografia.submetida", True),
        ("monografia.submetida", "monografia.publicada", False),
        ("#", "qualquer.coisa", True),
    ],
)
def test_casamento_topic(padrao, chave, esperado):
    assert casar_routing_key(padrao, chave) is esperado


def test_envelope_padrao():
    env = criar_envelope(
        "avaliacao.registrada",
        {"banca_id": uuid.uuid4(), "avaliacao_id": 1, "membro_id": 2},
        actor_id="u1",
        correlation_id="req-123",
    )
    assert set(env) == {
        "event_id",
        "type",
        "schema_version",
        "occurred_at",
        "producer",
        "correlation_id",
        "actor_id",
        "data",
    }
    assert env["schema_version"] == 1 and env["producer"] == "common-service"
    assert env["occurred_at"].endswith("Z") and isinstance(env["data"]["banca_id"], str)


def test_schema_invalido_rejeitado():
    with pytest.raises(EventoInvalido):
        criar_envelope("avaliacao.registrada", {"banca_id": 1})
    with pytest.raises(EventoInvalido):
        criar_envelope("tipo.inexistente", {})


def test_registrar_evento_grava_outbox():
    ev = registrar_evento("repositorio.indexado", {"monografia_id": "m1"})
    row = OutboxEvento.objects.get(pk=ev.pk)
    assert row.publicado_em is None and row.payload["event_id"] == str(row.id)


class PublisherFalso:
    def __init__(self, falhar_em: int | None = None):
        self.publicados: list[dict] = []
        self.falhar_em = falhar_em

    def publicar(self, envelope):
        if self.falhar_em is not None and len(self.publicados) == self.falhar_em:
            raise ConnectionError("broker fora")
        self.publicados.append(envelope)

    def fechar(self):
        pass


def test_publish_outbox_publica_e_marca():
    from tcc_common.events.management.commands.publish_outbox import publicar_lote

    for i in range(3):
        registrar_evento("repositorio.indexado", {"monografia_id": f"m{i}"})
    pub = PublisherFalso()
    assert publicar_lote(pub) == 3
    assert OutboxEvento.objects.filter(publicado_em__isnull=True).count() == 0
    assert [e["data"]["monografia_id"] for e in pub.publicados] == ["m0", "m1", "m2"]  # ordem preservada
    assert publicar_lote(pub) == 0


def test_publish_outbox_falha_mantem_pendente():
    from tcc_common.events.management.commands.publish_outbox import publicar_lote

    for i in range(3):
        registrar_evento("repositorio.indexado", {"monografia_id": f"m{i}"})
    assert publicar_lote(PublisherFalso(falhar_em=1)) == 1
    pendentes = OutboxEvento.objects.filter(publicado_em__isnull=True)
    assert pendentes.count() == 2
    assert pendentes.first().tentativas == 1 and "broker fora" in pendentes.first().ultimo_erro


def test_token_mascarado_no_outbox_apos_publicacao():
    from tcc_common.events.management.commands.publish_outbox import publicar_lote

    registrar_evento(
        "banca.convite_enviado",
        {
            "banca_id": "b",
            "monografia_id": "m",
            "membro": {"email": "x@y"},
            "expira_em": "2026-01-01",
            "token": "segredo-123",
        },
    )
    pub = PublisherFalso()
    publicar_lote(pub)
    assert pub.publicados[0]["data"]["token"] == "segredo-123"  # vai na mensagem
    assert OutboxEvento.objects.get().payload["data"]["token"] == "***"  # não fica no banco


def test_processar_evento_idempotente():
    chamadas = []
    env = criar_envelope("repositorio.indexado", {"monografia_id": "m"})
    assert processar_evento(env, lambda e: chamadas.append(e)) == "processado"
    assert processar_evento(env, lambda e: chamadas.append(e)) == "duplicado"
    assert len(chamadas) == 1 and EventoProcessado.objects.count() == 1


def test_processar_evento_erro_reverte_e_nao_marca():
    env = criar_envelope("repositorio.indexado", {"monografia_id": "m"})

    def handler(e):
        registrar_evento("repositorio.indexado", {"monografia_id": "efeito"})
        raise RuntimeError("falhou")

    with pytest.raises(RuntimeError):
        processar_evento(env, handler)
    assert not EventoProcessado.objects.exists()
    assert not OutboxEvento.objects.exists()  # efeito revertido junto


class CanalFalso:
    def __init__(self):
        self.acks, self.nacks, self.publicados = [], [], []

    def basic_ack(self, delivery_tag):
        self.acks.append(delivery_tag)

    def basic_nack(self, delivery_tag, requeue):
        self.nacks.append((delivery_tag, requeue))

    def basic_publish(self, exchange, routing_key, body, properties):
        self.publicados.append((exchange, routing_key, properties.headers))


def _mensagem(env, tentativas=0):
    method = SimpleNamespace(delivery_tag=7)
    props = SimpleNamespace(
        headers={"x-tentativas": tentativas} if tentativas else None,
        message_id=env["event_id"],
        correlation_id=None,
        type=env["type"],
    )
    return method, props, json.dumps(env).encode()


def _consumer(handler):
    c = BaseConsumer("teste", {"repositorio.indexado": handler})
    c.filas["repositorio.indexado"] = rabbit.FilasConsumer(
        "teste.repositorio.indexado",
        (
            "teste.repositorio.indexado.retry.1",
            "teste.repositorio.indexado.retry.2",
            "teste.repositorio.indexado.retry.3",
        ),
        "teste.repositorio.indexado.dlq",
    )
    return c


def test_consumer_ack_apos_sucesso():
    canal = CanalFalso()
    env = criar_envelope("repositorio.indexado", {"monografia_id": "m"})
    _consumer(lambda e: None)._on_message(canal, *_mensagem(env), binding="repositorio.indexado")
    assert canal.acks == [7] and not canal.nacks
    assert EventoProcessado.objects.filter(event_id=env["event_id"]).exists()


def test_consumer_falha_vai_para_retry_com_backoff():
    canal = CanalFalso()
    env = criar_envelope("repositorio.indexado", {"monografia_id": "m"})

    def quebra(e):
        raise ValueError("x")

    c = _consumer(quebra)
    for tentativa in range(3):
        c._on_message(canal, *_mensagem(env, tentativas=tentativa), binding="repositorio.indexado")
    assert [p[1] for p in canal.publicados] == [
        "teste.repositorio.indexado.retry.1",
        "teste.repositorio.indexado.retry.2",
        "teste.repositorio.indexado.retry.3",
    ]
    assert [p[2]["x-tentativas"] for p in canal.publicados] == [1, 2, 3]
    assert not canal.nacks


def test_mensagem_veneno_vai_para_dlq_e_chama_falha_definitiva():
    canal = CanalFalso()
    env = criar_envelope("repositorio.indexado", {"monografia_id": "m"})
    registros = []

    def quebra(e):
        raise ValueError("veneno")

    quebra.falha_definitiva = lambda e, exc: registros.append(str(exc))
    _consumer(quebra)._on_message(canal, *_mensagem(env, tentativas=3), binding="repositorio.indexado")
    assert canal.nacks == [(7, False)]  # dead-letter -> tcc.dlx -> <fila>.dlq
    assert registros == ["veneno"]


def test_mensagem_malformada_vai_direto_para_dlq():
    canal = CanalFalso()
    method = SimpleNamespace(delivery_tag=9)
    props = SimpleNamespace(headers=None, message_id="x", correlation_id=None, type=None)
    _consumer(lambda e: None)._on_message(canal, method, props, b"nao-json", binding="repositorio.indexado")
    assert canal.nacks == [(9, False)]


def test_nome_fila():
    assert rabbit.nome_fila("monografias", "cadastro.#") == "monografias.cadastro.todos"
    assert rabbit.nome_fila("bancas", "monografia.*") == "bancas.monografia.qualquer"

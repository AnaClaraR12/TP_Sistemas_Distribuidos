"""Sem Redis o dashboard continua respondendo, só que sem cache."""

import pytest
import redis

from apps.relatorios import metricas

pytestmark = pytest.mark.django_db


class RedisFora:
    def __getattr__(self, nome):
        def falha(*args, **kwargs):
            raise redis.ConnectionError("redis fora")

        return falha


def test_relatorio_sem_redis_calcula_direto(ator, dados, monkeypatch):
    monkeypatch.setattr(metricas, "get_redis", lambda: RedisFora())
    r = ator("admin").client.get("/api/relatorios/resumo/")
    assert r.status_code == 200
    assert r["X-Cache"] == "MISS"
    assert r.data["dados"]["total"] == 5


def test_invalidar_sem_redis_nao_quebra_consumer(monkeypatch):
    monkeypatch.setattr(metricas, "get_redis", lambda: RedisFora())
    metricas.invalidar_cache()


def test_chave_de_cache_do_coordenador_nao_depende_da_ordem_dos_cursos():
    from tcc_common.auth.usuario import UsuarioToken

    a = UsuarioToken(id="1", email="c@x", papel="coordenador", professor_id="p", curso_ids=("c2", "c1"))
    b = UsuarioToken(id="1", email="c@x", papel="coordenador", professor_id="p", curso_ids=("c1", "c2"))
    assert metricas.escopo_do_usuario(a)[0] == metricas.escopo_do_usuario(b)[0] == "curso:c1,c2"

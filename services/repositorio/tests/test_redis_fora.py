"""Busca pública continua funcionando quando o Redis cai: o cache é só uma otimização."""

import pytest
import redis

from apps.indexacao import cache as modcache
from apps.indexacao import views as modviews
from tcc_common.cache import redis as modredis
from tcc_common.cache.redis import get_redis

pytestmark = pytest.mark.django_db


class RedisFora:
    def __getattr__(self, nome):
        def falha(*args, **kwargs):
            raise redis.ConnectionError("redis fora")

        return falha


@pytest.fixture
def redis_fora(monkeypatch):
    for modulo in (modcache, modviews, modredis):
        monkeypatch.setattr(modulo, "get_redis", lambda: RedisFora())


def test_busca_sem_redis_responde_do_banco(publicar, api, redis_fora):
    publicar()
    r = api.get("/api/repositorio/monografias/?busca=quiescente")
    assert r.status_code == 200
    assert r["X-Cache"] == "MISS"
    assert r.data["count"] == 1


def test_detalhe_sem_redis_omite_contador_de_downloads(publicar, api, redis_fora):
    mid = publicar()
    r = api.get(f"/api/repositorio/monografias/{mid}/")
    assert r.status_code == 200
    assert r.data["downloads"] is None


def test_invalidar_cache_sem_redis_nao_quebra_publicacao(redis_fora):
    modcache.invalidar_cache_busca()


def test_cache_desligado_nao_grava_no_redis(publicar, api, settings):
    publicar()
    settings.BUSCA_CACHE_ATIVO = False
    r = api.get("/api/repositorio/monografias/?busca=quiescente")
    assert r["X-Cache"] == "BYPASS"
    assert [k for k in get_redis().keys("busca:*") if k != "busca:versao"] == []

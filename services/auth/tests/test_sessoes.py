"""Sessões do Django Admin/allauth ficam no cache "sessoes" (Redis em produção)."""

import pytest
from django.conf import settings
from django.core.cache import caches

pytestmark = pytest.mark.django_db


def test_sessao_do_admin_vai_para_o_cache_de_sessoes(client, criar_usuario):
    admin = criar_usuario(email="admin@ufvjm.edu.br", papel="admin")
    client.force_login(admin)
    chave = client.session.session_key
    assert settings.SESSION_ENGINE == "django.contrib.sessions.backends.cache"
    assert caches["sessoes"].get(f"django.contrib.sessions.cache{chave}") is not None


def test_sessoes_usam_redis_quando_redis_url_e_real(monkeypatch):
    from tcc_common.settings_base import construir

    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    cfg = construir(servico="auth", apps=[])
    assert cfg["CACHES"]["sessoes"]["BACKEND"] == "django_redis.cache.RedisCache"
    assert cfg["CACHES"]["sessoes"]["LOCATION"] == "redis://redis:6379/0"

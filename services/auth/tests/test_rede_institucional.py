"""Área administrativa somente pela rede institucional (IP/VPN)."""

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _cidrs(settings):
    settings.INSTITUTIONAL_CIDRS = "10.0.0.0/8,127.0.0.1/32"
    settings.TRUSTED_PROXY_CIDRS = "172.16.0.0/12"


def test_admin_fora_da_rede_403(client):
    r = client.get("/admin/login/", REMOTE_ADDR="203.0.113.10")
    assert r.status_code == 403
    assert r.json()["codigo"] == "fora_da_rede_institucional"


def test_admin_dentro_da_rede_200(client):
    assert client.get("/admin/login/", REMOTE_ADDR="10.20.30.40").status_code == 200


def test_spoof_x_real_ip_ignorado_fora_do_gateway(client):
    r = client.get(
        "/admin/login/", REMOTE_ADDR="203.0.113.10", HTTP_X_REAL_IP="10.0.0.5", HTTP_X_FORWARDED_FOR="10.0.0.5"
    )
    assert r.status_code == 403


def test_via_gateway_usa_x_real_ip(client):
    assert client.get("/admin/login/", REMOTE_ADDR="172.18.0.2", HTTP_X_REAL_IP="10.0.0.5").status_code == 200
    assert client.get("/admin/login/", REMOTE_ADDR="172.18.0.2", HTTP_X_REAL_IP="8.8.8.8").status_code == 403


def test_via_gateway_xff_usa_ultimo_ip(client):
    # cliente forja "10.0.0.9" no início; o gateway anexou o IP real (8.8.4.4) ao final
    r = client.get("/admin/login/", REMOTE_ADDR="172.18.0.2", HTTP_X_FORWARDED_FOR="10.0.0.9, 8.8.4.4")
    assert r.status_code == 403


def test_api_admin_tambem_protegida(ator):
    adm = ator("admin")
    assert adm.client.get("/api/auth/admin/usuarios/", REMOTE_ADDR="203.0.113.1").status_code == 403
    assert adm.client.get("/api/auth/admin/usuarios/", REMOTE_ADDR="10.0.0.1").status_code == 200


def test_api_admin_exige_papel_admin(ator):
    assert ator("coordenador").client.get("/api/auth/admin/usuarios/", REMOTE_ADDR="10.0.0.1").status_code == 403


def test_rotas_publicas_nao_afetadas(api):
    assert api.get("/health/", REMOTE_ADDR="203.0.113.1").status_code == 200
    assert api.get("/.well-known/jwks.json", REMOTE_ADDR="203.0.113.1").status_code == 200

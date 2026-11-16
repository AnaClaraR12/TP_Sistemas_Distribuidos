"""Área administrativa só a partir da rede institucional (IP/VPN)."""

import ipaddress
import re
from functools import lru_cache

from django.conf import settings
from django.http import JsonResponse

# Django Admin e as rotas /api/<servico>/admin/
ROTAS_ADMINISTRATIVAS = re.compile(r"^/admin/|^/api/[^/]+/admin/")


@lru_cache(maxsize=8)
def _redes(valor: str) -> tuple[ipaddress._BaseNetwork, ...]:
    return tuple(ipaddress.ip_network(c.strip(), strict=False) for c in valor.split(",") if c.strip())


def _pertence(ip: str, cidrs: str) -> bool:
    try:
        endereco = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(endereco in rede for rede in _redes(cidrs))


def ip_do_cliente(request) -> str:
    """IP real do cliente.

    ``X-Real-IP`` só é aceito quando a conexão vem de um proxy confiável (o gateway,
    ``TRUSTED_PROXY_CIDRS``); caso contrário usamos ``REMOTE_ADDR`` — evita spoofing.
    """
    remoto = request.META.get("REMOTE_ADDR", "")
    if _pertence(remoto, getattr(settings, "TRUSTED_PROXY_CIDRS", "")):
        real = request.META.get("HTTP_X_REAL_IP", "").strip()
        if real:
            return real
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if xff:
            # o gateway ANEXA o IP que viu: o último item é o confiável
            return xff.split(",")[-1].strip()
    return remoto


class InstitutionalNetworkMiddleware:
    """Retorna 403 para rotas administrativas acessadas de fora de ``INSTITUTIONAL_CIDRS``."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if ROTAS_ADMINISTRATIVAS.match(request.path):
            ip = ip_do_cliente(request)
            if not _pertence(ip, settings.INSTITUTIONAL_CIDRS):
                return JsonResponse(
                    {
                        "codigo": "fora_da_rede_institucional",
                        "mensagem": "A área administrativa só pode ser acessada pela rede institucional (IP/VPN).",
                        "detalhes": {},
                    },
                    status=403,
                )
        return self.get_response(request)

from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from tcc_common.api.health import health, ready


def urls_base(servico: str) -> list:
    return [
        path("health/", health, name="health"),
        path("ready/", ready, name="ready"),
        path(f"api/{servico}/health/", health),
        path(f"api/{servico}/ready/", ready),
        path(f"api/{servico}/schema/", SpectacularAPIView.as_view(), name="schema"),
        path(f"api/{servico}/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    ]

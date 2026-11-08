from django.urls import include, path

from apps.monografias.views import ArquivoInternoView, MonografiaInternaView, MonografiaViewSet
from tcc_common.api.routers import RouterBarraOpcional
from tcc_common.api.urls import urls_base

# trailing_slash "/?" aceita /api/monografias e /api/monografias/ (exemplos do enunciado)
router = RouterBarraOpcional()
router.register("api/monografias", MonografiaViewSet, basename="monografia")

urlpatterns = [
    *urls_base("monografias"),
    path("internal/monografias/<uuid:pk>/", MonografiaInternaView.as_view()),
    path("internal/monografias/<uuid:pk>/arquivo/", ArquivoInternoView.as_view()),
    path("", include(router.urls)),
]

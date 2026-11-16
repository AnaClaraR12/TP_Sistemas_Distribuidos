from django.urls import include, path

from apps.bancas import views
from tcc_common.api.routers import RouterBarraOpcional
from tcc_common.api.urls import urls_base

router = RouterBarraOpcional()
router.register("api/bancas", views.BancaViewSet, basename="banca")
router.register("api/avaliacoes", views.AvaliacaoViewSet, basename="avaliacao")

avaliacao_aninhada = views.AvaliacaoViewSet.as_view(
    {"get": "retrieve", "patch": "partial_update", "put": "update", "delete": "destroy"}
)

urlpatterns = [
    *urls_base("bancas"),
    # acesso externo por token (antes do router para não colidir com /api/bancas/{id}/)
    path("api/bancas/externo/minha-banca/", views.ExternoMinhaBancaView.as_view()),
    path("api/bancas/externo/confirmar/", views.ExternoConfirmarView.as_view()),
    path("api/bancas/externo/avaliacao/", views.ExternoAvaliacaoView.as_view()),
    path("api/bancas/externo/arquivo/", views.ExternoArquivoView.as_view()),
    path("api/bancas/<uuid:banca_pk>/avaliacoes/<uuid:pk>/", avaliacao_aninhada),
    path("", include(router.urls)),
]

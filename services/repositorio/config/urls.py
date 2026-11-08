from django.urls import include, path

from apps.indexacao import views
from tcc_common.api.routers import RouterBarraOpcional
from tcc_common.api.urls import urls_base

router = RouterBarraOpcional()
router.register("api/repositorio/monografias", views.MonografiaPublicaViewSet, basename="monografia-publica")

urlpatterns = [
    *urls_base("repositorio"),
    path("api/repositorio/cursos/", views.CursosPublicosView.as_view(), name="cursos-publicos"),
    path("api/repositorio/orientadores/", views.OrientadoresPublicosView.as_view(), name="orientadores-publicos"),
    path("", include(router.urls)),
]

from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.academico.views import AlunoViewSet, CursoViewSet, ProfessorViewSet
from apps.auditoria.views import AuditoriaViewSet
from apps.contas import views as contas
from tcc_common.api.urls import urls_base

router = DefaultRouter()
router.register("cursos", CursoViewSet, basename="curso")
router.register("professores", ProfessorViewSet, basename="professor")
router.register("alunos", AlunoViewSet, basename="aluno")
router.register("auditoria", AuditoriaViewSet, basename="auditoria")

admin_router = DefaultRouter()
admin_router.register("usuarios", contas.UsuarioAdminViewSet, basename="usuario-admin")

admin.site.site_header = "Sistema de Monografias — Administração"

urlpatterns = [
    *urls_base("auth"),
    path("admin/", admin.site.urls),
    path(".well-known/jwks.json", contas.jwks_view, name="jwks"),
    path("api/auth/.well-known/jwks.json", contas.jwks_view),
    path("api/auth/token/", contas.TokenView.as_view(), name="token"),
    path("api/auth/token/refresh/", contas.RefreshView.as_view(), name="token-refresh"),
    path("api/auth/logout/", contas.LogoutView.as_view(), name="logout"),
    path("api/auth/me/", contas.MeView.as_view(), name="me"),
    path("api/auth/me/dashboard-config/", contas.DashboardConfigView.as_view(), name="dashboard-config"),
    path("api/auth/contas/", include("allauth.urls")),
    path("api/auth/admin/", include(admin_router.urls)),
    path("api/auth/", include(router.urls)),
]

from django.urls import path

from apps.notificacoes.views import MarcarLidaView, MinhasNotificacoesView
from tcc_common.api.urls import urls_base

urlpatterns = [
    *urls_base("notificacoes"),
    path("api/notificacoes/minhas/", MinhasNotificacoesView.as_view(), name="minhas"),
    path("api/notificacoes/<uuid:pk>/lida/", MarcarLidaView.as_view(), name="lida"),
]

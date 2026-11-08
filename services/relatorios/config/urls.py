from django.urls import re_path

from apps.relatorios.views import RelatorioView
from tcc_common.api.urls import urls_base

urlpatterns = [
    *urls_base("relatorios"),
    re_path(r"^api/relatorios/(?P<nome>[a-z\-]+)/?$", RelatorioView.as_view(), name="relatorio"),
]

"""GET /api/relatorios/<nome>/ — escopo pelo papel (Anexo D), cache Redis de 60 s."""

from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.relatorios import metricas
from tcc_common.auth.permissions import IsAutenticado


class RelatorioView(APIView):
    permission_classes = [IsAutenticado]

    @extend_schema(responses={200: dict})
    def get(self, request, nome: str):
        if nome not in metricas.RELATORIOS:
            raise Http404
        escopo, filtro = metricas.escopo_do_usuario(request.user)
        dados, status = metricas.com_cache(nome, escopo, lambda: metricas.calcular(nome, filtro))
        resp = Response({"relatorio": nome, "escopo": escopo.split(":")[0], "dados": dados})
        resp["X-Cache"] = status
        return resp

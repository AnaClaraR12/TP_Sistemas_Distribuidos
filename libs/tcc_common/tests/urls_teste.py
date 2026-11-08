from django.urls import path
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from tcc_common.api.exceptions import ErroNegocio
from tcc_common.api.urls import urls_base
from tcc_common.auth.permissions import IsServicoInterno


class _S(serializers.Serializer):
    nome = serializers.CharField()


class ErroView(APIView):
    permission_classes: list = []

    def get(self, request):
        raise ErroNegocio("Regra violada.", codigo="regra_x", detalhes={"a": 1})

    def post(self, request):
        _S(data=request.data).is_valid(raise_exception=True)
        return Response({})


class InternoView(APIView):
    authentication_classes: list = []
    permission_classes = [IsServicoInterno]

    def get(self, request):
        return Response({"ok": True})


urlpatterns = [*urls_base("common"), path("erro/", ErroView.as_view()), path("interno/", InternoView.as_view())]

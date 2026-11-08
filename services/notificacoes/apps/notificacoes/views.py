"""Alertas in-app: GET /api/notificacoes/minhas/ e POST /api/notificacoes/{id}/lida/."""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notificacoes.models import Notificacao
from tcc_common.auth.permissions import IsAutenticado


class NotificacaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notificacao
        fields = ["id", "tipo", "assunto", "corpo", "status", "criada_em", "enviada_em", "lida_em"]


class MinhasNotificacoesView(generics.ListAPIView):
    permission_classes = [IsAutenticado]
    serializer_class = NotificacaoSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # geração do schema OpenAPI (sem usuário)
            return Notificacao.objects.none()
        qs = Notificacao.objects.filter(destinatario_email=self.request.user.email.lower())
        if self.request.query_params.get("nao_lidas") in ("1", "true"):
            qs = qs.filter(lida_em__isnull=True)
        return qs


class MarcarLidaView(APIView):
    permission_classes = [IsAutenticado]

    @extend_schema(request=None, responses=NotificacaoSerializer)
    def post(self, request, pk):
        n = get_object_or_404(Notificacao, pk=pk, destinatario_email=request.user.email.lower())
        if n.lida_em is None:
            n.lida_em = timezone.now()
            n.save(update_fields=["lida_em"])
        return Response(NotificacaoSerializer(n).data)

"""Consulta de auditoria (admin/coordenador) com filtros por usuário, ação e período."""

import django_filters
from rest_framework import serializers, viewsets

from apps.auditoria.models import RegistroAuditoria
from tcc_common.auth.permissions import IsCoordenador


class RegistroAuditoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegistroAuditoria
        fields = "__all__"


class AuditoriaFiltro(django_filters.FilterSet):
    inicio = django_filters.IsoDateTimeFilter(field_name="criado_em", lookup_expr="gte")
    fim = django_filters.IsoDateTimeFilter(field_name="criado_em", lookup_expr="lte")
    acao = django_filters.CharFilter(lookup_expr="iexact")
    usuario = django_filters.UUIDFilter(field_name="usuario_id")
    email = django_filters.CharFilter(field_name="usuario_email", lookup_expr="icontains")

    class Meta:
        model = RegistroAuditoria
        fields = ["usuario", "acao", "recurso", "recurso_id", "nivel", "servico_origem", "inicio", "fim", "email"]


class AuditoriaViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsCoordenador]
    queryset = RegistroAuditoria.objects.all()
    serializer_class = RegistroAuditoriaSerializer
    filterset_class = AuditoriaFiltro

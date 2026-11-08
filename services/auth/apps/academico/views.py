"""CRUD de Curso, Professor e Aluno (escrita: coordenador/admin)."""

from __future__ import annotations

from django.db import transaction
from django.db.models import ProtectedError
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied

from apps.academico import servicos
from apps.academico.models import Aluno, Curso, Professor
from apps.academico.serializers import AlunoSerializer, CursoSerializer, ProfessorSerializer
from tcc_common.api.exceptions import ErroNegocio
from tcc_common.audit.auditoria import AuditoriaViewSetMixin
from tcc_common.audit.historico import HistoricoMixin
from tcc_common.auth.permissions import IsAutenticado, IsCoordenador, papeis


class _EscritaCoordenador:
    """Leitura conforme ``permissoes_leitura``; escrita só coordenador/admin."""

    permissoes_leitura = [IsAutenticado]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [p() for p in self.permissoes_leitura]
        return [IsCoordenador()]


class CursoViewSet(_EscritaCoordenador, AuditoriaViewSetMixin, HistoricoMixin, viewsets.ModelViewSet):
    queryset = Curso.objects.select_related("coordenador").all()
    serializer_class = CursoSerializer
    filterset_fields = ["codigo", "coordenador"]
    auditoria_recurso = "curso"

    @transaction.atomic
    def perform_destroy(self, instance):
        coord = instance.coordenador
        pk = instance.pk
        try:
            super().perform_destroy(instance)
        except ProtectedError as exc:
            raise ErroNegocio("Curso possui alunos vinculados.", codigo="curso_com_alunos") from exc
        servicos.sincronizar_papel_coordenador(coord)
        servicos.publicar_exclusao("curso", pk)


class ProfessorViewSet(_EscritaCoordenador, AuditoriaViewSetMixin, HistoricoMixin, viewsets.ModelViewSet):
    queryset = Professor.objects.select_related("user").all()
    serializer_class = ProfessorSerializer
    filterset_fields = ["departamento"]
    auditoria_recurso = "professor"

    @transaction.atomic
    def perform_destroy(self, instance):
        pk, user = instance.pk, instance.user
        super().perform_destroy(instance)
        user.delete()
        servicos.publicar_exclusao("professor", pk)


class AlunoViewSet(_EscritaCoordenador, AuditoriaViewSetMixin, HistoricoMixin, viewsets.ModelViewSet):
    serializer_class = AlunoSerializer
    filterset_fields = ["curso", "orientador_atual", "matricula"]
    permissoes_leitura = [papeis("admin", "coordenador", "professor", "aluno")]
    auditoria_recurso = "aluno"

    def get_queryset(self):
        qs = Aluno.objects.select_related("curso", "orientador_atual")
        if getattr(self, "swagger_fake_view", False):  # geração do schema OpenAPI (sem usuário)
            return qs.none()
        u = self.request.user
        if u.papel == "admin":
            return qs
        if u.papel == "coordenador":
            return qs.filter(curso_id__in=u.curso_ids) | qs.filter(orientador_atual_id=u.professor_id)
        if u.papel == "professor":
            return qs.filter(orientador_atual_id=u.professor_id)
        return qs.filter(id=u.aluno_id)

    def _exigir_curso_do_coordenador(self, curso) -> None:
        u = self.request.user
        if u.papel == "coordenador" and str(getattr(curso, "pk", curso)) not in {str(c) for c in u.curso_ids}:
            raise PermissionDenied("O coordenador só gerencia alunos do próprio curso.")

    def perform_create(self, serializer):
        self._exigir_curso_do_coordenador(serializer.validated_data["curso"])
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self._exigir_curso_do_coordenador(serializer.validated_data.get("curso", serializer.instance.curso))
        super().perform_update(serializer)

    @transaction.atomic
    def perform_destroy(self, instance):
        pk, user = instance.pk, instance.user
        super().perform_destroy(instance)
        user.delete()
        servicos.publicar_exclusao("aluno", pk)

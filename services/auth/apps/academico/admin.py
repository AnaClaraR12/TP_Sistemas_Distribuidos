from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.academico.models import Aluno, Curso, Professor
from apps.auditoria.models import RegistroAuditoria


@admin.register(Curso)
class CursoAdmin(SimpleHistoryAdmin):
    list_display = ["codigo", "nome", "coordenador"]
    search_fields = ["codigo", "nome"]


@admin.register(Professor)
class ProfessorAdmin(SimpleHistoryAdmin):
    list_display = ["nome", "email", "departamento"]
    search_fields = ["nome", "email"]


@admin.register(Aluno)
class AlunoAdmin(SimpleHistoryAdmin):
    list_display = ["nome", "matricula", "curso", "orientador_atual"]
    search_fields = ["nome", "matricula", "email"]
    list_filter = ["curso"]


@admin.register(RegistroAuditoria)
class RegistroAuditoriaAdmin(admin.ModelAdmin):
    list_display = ["criado_em", "acao", "recurso", "recurso_id", "usuario_email", "ip", "nivel", "servico_origem"]
    list_filter = ["nivel", "servico_origem", "acao"]
    search_fields = ["usuario_email", "recurso_id"]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

from django.db import transaction
from rest_framework import serializers

from apps.academico import servicos
from apps.academico.models import Aluno, Curso, Professor
from apps.contas.models import Papel


class CursoSerializer(serializers.ModelSerializer):
    coordenador_nome = serializers.CharField(source="coordenador.nome", read_only=True, default=None)

    class Meta:
        model = Curso
        fields = ["id", "nome", "codigo", "coordenador", "coordenador_nome", "criado_em", "atualizado_em"]
        read_only_fields = ["id", "criado_em", "atualizado_em"]

    @transaction.atomic
    def save(self, **kwargs):
        anterior = self.instance.coordenador if self.instance else None
        curso = super().save(**kwargs)
        servicos.sincronizar_papel_coordenador(curso.coordenador)
        if anterior and anterior != curso.coordenador:
            servicos.sincronizar_papel_coordenador(anterior)
            servicos.publicar_professor(anterior)
        if curso.coordenador:
            servicos.publicar_professor(curso.coordenador)
        servicos.publicar_curso(curso)
        return curso


class ProfessorSerializer(serializers.ModelSerializer):
    papel = serializers.CharField(source="user.papel", read_only=True)

    class Meta:
        model = Professor
        fields = ["id", "nome", "email", "departamento", "area_pesquisa", "papel", "criado_em", "atualizado_em"]
        read_only_fields = ["id", "papel", "criado_em", "atualizado_em"]

    def validate_email(self, value: str) -> str:
        if self.instance and value.lower() != self.instance.email:
            raise serializers.ValidationError("O e-mail do professor não pode ser alterado.")
        return value.lower()

    @transaction.atomic
    def create(self, validated_data):
        user = servicos.criar_usuario_vinculado(validated_data["email"], validated_data["nome"], Papel.PROFESSOR)
        prof = Professor.objects.create(user=user, **validated_data)
        servicos.publicar_professor(prof)
        return prof

    @transaction.atomic
    def update(self, instance, validated_data):
        prof = super().update(instance, validated_data)
        if prof.user.nome != prof.nome:
            prof.user.nome = prof.nome
            prof.user.save(update_fields=["nome"])
        servicos.publicar_professor(prof)
        return prof


class AlunoSerializer(serializers.ModelSerializer):
    curso_nome = serializers.CharField(source="curso.nome", read_only=True)
    orientador_nome = serializers.CharField(source="orientador_atual.nome", read_only=True, default=None)

    class Meta:
        model = Aluno
        fields = [
            "id",
            "nome",
            "matricula",
            "email",
            "curso",
            "curso_nome",
            "orientador_atual",
            "orientador_nome",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = ["id", "criado_em", "atualizado_em"]

    def validate_email(self, value: str) -> str:
        if self.instance and value.lower() != self.instance.email:
            raise serializers.ValidationError("O e-mail do aluno não pode ser alterado.")
        return value.lower()

    @transaction.atomic
    def create(self, validated_data):
        user = servicos.criar_usuario_vinculado(validated_data["email"], validated_data["nome"], Papel.ALUNO)
        aluno = Aluno.objects.create(user=user, **validated_data)
        servicos.publicar_aluno(aluno)
        return aluno

    @transaction.atomic
    def update(self, instance, validated_data):
        aluno = super().update(instance, validated_data)
        servicos.publicar_aluno(aluno)
        return aluno

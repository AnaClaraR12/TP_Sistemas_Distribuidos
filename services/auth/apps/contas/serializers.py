from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(required=False)


class MeSerializer(serializers.ModelSerializer):
    vinculos = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "nome", "papel", "is_active", "last_login", "ultimo_login_ip", "vinculos"]

    def get_vinculos(self, obj) -> dict:
        dados: dict = {}
        aluno = getattr(obj, "aluno", None) if hasattr(obj, "aluno") else None
        professor = getattr(obj, "professor", None) if hasattr(obj, "professor") else None
        if aluno:
            dados["aluno"] = {
                "id": str(aluno.id),
                "matricula": aluno.matricula,
                "curso": {"id": str(aluno.curso_id), "nome": aluno.curso.nome},
                "orientador_atual": (
                    {"id": str(aluno.orientador_atual_id), "nome": aluno.orientador_atual.nome}
                    if aluno.orientador_atual_id
                    else None
                ),
            }
        if professor:
            dados["professor"] = {
                "id": str(professor.id),
                "departamento": professor.departamento,
                "cursos_coordenados": [{"id": str(c.id), "nome": c.nome} for c in professor.cursos_coordenados.all()],
            }
        return dados


class UsuarioAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "nome", "papel", "is_active", "last_login", "ultimo_login_ip", "date_joined"]
        read_only_fields = ["id", "email", "last_login", "ultimo_login_ip", "date_joined"]

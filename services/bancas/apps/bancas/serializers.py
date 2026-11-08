from rest_framework import serializers

from apps.bancas.models import Avaliacao, Banca, MembroBanca, MonografiaRef


class MembroEntradaSerializer(serializers.Serializer):
    tipo = serializers.ChoiceField(choices=MembroBanca.Tipo.choices)
    professor_id = serializers.UUIDField(required=False)
    nome = serializers.CharField(required=False, max_length=150)
    email = serializers.EmailField(required=False)
    instituicao = serializers.CharField(required=False, allow_blank=True, max_length=200)
    funcao = serializers.ChoiceField(choices=MembroBanca.Funcao.choices, required=False)

    def validate(self, attrs):
        if attrs["tipo"] == "interno" and not attrs.get("professor_id"):
            raise serializers.ValidationError("Membro interno exige professor_id.")
        if attrs["tipo"] == "externo" and not (attrs.get("nome") and attrs.get("email")):
            raise serializers.ValidationError("Membro externo exige nome e e-mail.")
        return attrs


class MembroSerializer(serializers.ModelSerializer):
    avaliou = serializers.SerializerMethodField()

    class Meta:
        model = MembroBanca
        fields = [
            "id",
            "tipo",
            "professor_id",
            "nome",
            "email",
            "instituicao",
            "funcao",
            "confirmacao",
            "confirmado_em",
            "token_expira_em",
            "token_revogado",
            "avaliou",
        ]
        read_only_fields = fields

    def get_avaliou(self, obj) -> bool:
        return obj.avaliacoes.exists()


class BancaCriacaoSerializer(serializers.Serializer):
    monografia_id = serializers.UUIDField()
    data_hora_inicio = serializers.DateTimeField()
    duracao_minutos = serializers.IntegerField(required=False, min_value=15, max_value=600)
    local = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=200)
    link = serializers.URLField(required=False, allow_blank=True, allow_null=True, max_length=500)
    membros = MembroEntradaSerializer(many=True)


class BancaEdicaoSerializer(serializers.Serializer):
    data_hora_inicio = serializers.DateTimeField(required=False)
    duracao_minutos = serializers.IntegerField(required=False, min_value=15, max_value=600)
    local = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=200)
    link = serializers.URLField(required=False, allow_blank=True, allow_null=True, max_length=500)


class BancaSerializer(serializers.ModelSerializer):
    membros = MembroSerializer(many=True, read_only=True)
    data_hora_fim = serializers.DateTimeField(read_only=True)
    monografia = serializers.SerializerMethodField()
    total_avaliacoes = serializers.SerializerMethodField()

    class Meta:
        model = Banca
        fields = [
            "id",
            "monografia_id",
            "monografia",
            "data_hora_inicio",
            "data_hora_fim",
            "duracao_minutos",
            "local",
            "link",
            "status",
            "resultado_final",
            "media_final",
            "exige_correcao",
            "resultado_calculado_em",
            "criada_por_id",
            "motivo_cancelamento",
            "membros",
            "total_avaliacoes",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = fields

    def get_monografia(self, obj) -> dict | None:
        ref = MonografiaRef.objects.filter(pk=obj.monografia_id).first()
        if not ref:
            return None
        return {
            "titulo": ref.titulo,
            "status": ref.status,
            "aluno_id": str(ref.aluno_id or ""),
            "orientador_id": str(ref.orientador_id or ""),
        }

    def get_total_avaliacoes(self, obj) -> int:
        return obj.avaliacoes.count()


class AvaliacaoEntradaSerializer(serializers.ModelSerializer):
    nota = serializers.DecimalField(max_digits=3, decimal_places=1, min_value=0, max_value=10)
    parecer = serializers.CharField(min_length=50)

    class Meta:
        model = Avaliacao
        fields = ["nota", "parecer", "recomendacao"]


class AvaliacaoSerializer(serializers.ModelSerializer):
    membro_nome = serializers.CharField(source="membro.nome", read_only=True)
    membro_tipo = serializers.CharField(source="membro.tipo", read_only=True)

    class Meta:
        model = Avaliacao
        fields = [
            "id",
            "banca",
            "membro",
            "membro_nome",
            "membro_tipo",
            "nota",
            "parecer",
            "recomendacao",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = fields


class RespostaSerializer(serializers.Serializer):
    resposta = serializers.ChoiceField(choices=["confirmado", "recusado"], default="confirmado")


class MotivoSerializer(serializers.Serializer):
    motivo = serializers.CharField(min_length=5, max_length=1000)

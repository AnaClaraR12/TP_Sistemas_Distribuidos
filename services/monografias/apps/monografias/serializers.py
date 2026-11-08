from rest_framework import serializers

from apps.monografias.models import DocumentoComplementar, Monografia, ProfessorRef


class DocumentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentoComplementar
        fields = [
            "id",
            "tipo",
            "arquivo_nome_original",
            "tamanho_bytes",
            "sha256",
            "assinado_validado",
            "validado_por_id",
            "validado_em",
            "enviado_por_id",
            "criado_em",
        ]
        read_only_fields = fields


class DocumentoUploadSerializer(serializers.Serializer):
    tipo = serializers.ChoiceField(choices=DocumentoComplementar.Tipo.choices)
    arquivo = serializers.FileField()


class ArquivoUploadSerializer(serializers.Serializer):
    arquivo = serializers.FileField()


class MotivoSerializer(serializers.Serializer):
    motivo = serializers.CharField(min_length=10, max_length=2000)


class MonografiaSerializer(serializers.ModelSerializer):
    """Campos editáveis explícitos (evita mass assignment); status é somente leitura."""

    palavras_chave = serializers.ListField(child=serializers.CharField(max_length=60), required=False)
    documentos = DocumentoSerializer(many=True, read_only=True)
    pendencias_publicacao = serializers.SerializerMethodField()
    orientador_nome = serializers.SerializerMethodField()

    class Meta:
        model = Monografia
        fields = [
            "id",
            "titulo",
            "resumo",
            "palavras_chave",
            "aluno_id",
            "orientador_id",
            "orientador_nome",
            "curso_id",
            "status",
            "aprovacao_orientador",
            "motivo_rejeicao",
            "aprovada_orientador_em",
            "submetida_em",
            "defendida_em",
            "resultado_banca",
            "exige_correcao",
            "correcao_validada",
            "arquivo_nome_original",
            "arquivo_tamanho_bytes",
            "arquivo_sha256",
            "arquivo_sha256_aprovado",
            "integridade_ok",
            "integridade_verificada_em",
            "texto_extraido",
            "publicada_em",
            "criado_em",
            "atualizado_em",
            "documentos",
            "pendencias_publicacao",
        ]
        read_only_fields = [f for f in fields if f not in ("titulo", "resumo", "palavras_chave", "orientador_id")]

    def get_pendencias_publicacao(self, obj) -> list[str]:
        return obj.pendencias_publicacao() if obj.status == "aprovada" else []

    def get_orientador_nome(self, obj) -> str | None:
        cache = self.context.setdefault("_profs", {})
        if obj.orientador_id not in cache:
            p = ProfessorRef.objects.filter(pk=obj.orientador_id).first() if obj.orientador_id else None
            cache[obj.orientador_id] = p.nome if p else None
        return cache[obj.orientador_id]

    def validate_palavras_chave(self, value: list[str]) -> list[str]:
        vistas, limpas = set(), []
        for p in value:
            p = " ".join(p.split()).strip()
            if p and p.lower() not in vistas:
                vistas.add(p.lower())
                limpas.append(p)
        return limpas

    def validate_orientador_id(self, value):
        if value and not ProfessorRef.objects.filter(pk=value).exists():
            raise serializers.ValidationError("Orientador não encontrado.")
        return value


class MonografiaCriacaoAdminSerializer(MonografiaSerializer):
    """Admin pode criar em nome de um aluno (informando aluno_id)."""

    aluno_id = serializers.UUIDField()

    class Meta(MonografiaSerializer.Meta):
        read_only_fields = [f for f in MonografiaSerializer.Meta.read_only_fields if f != "aluno_id"]

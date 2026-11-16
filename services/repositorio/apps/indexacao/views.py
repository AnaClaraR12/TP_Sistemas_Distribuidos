"""API PÚBLICA (sem autenticação, somente leitura) do repositório de monografias."""

import hashlib
import uuid
from pathlib import Path

import redis
from django.conf import settings
from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank
from django.db.models import Count, F, Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import exceptions, generics, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.indexacao.cache import obter_ou_calcular
from apps.indexacao.models import CursoRef, DocumentoIndexado, ProfessorRef
from tcc_common.cache.redis import get_redis
from tcc_common.texto import normalizar


class DocumentoPublicoSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="monografia_id")
    trecho = serializers.CharField(read_only=True, default=None)
    relevancia = serializers.FloatField(read_only=True, default=None)

    class Meta:
        model = DocumentoIndexado
        fields = [
            "id",
            "titulo",
            "resumo",
            "palavras_chave",
            "autor_nome",
            "orientador_id",
            "orientador_nome",
            "curso_id",
            "curso_nome",
            "ano_defesa",
            "paginas",
            "publicado_em",
            "arquivo_sha256",
            "trecho",
            "relevancia",
        ]


class _Publico:
    authentication_classes: list = []  # token inválido não pode quebrar a leitura pública
    permission_classes = [AllowAny]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if request.method == "GET" and response.status_code == 200:
            response["Cache-Control"] = f"public, max-age={settings.HTTP_CACHE_MAX_AGE}"
        return response


def _uuid(valor: str):
    try:
        return uuid.UUID(valor)
    except (ValueError, TypeError):
        return None


FILTROS = [
    OpenApiParameter(n, str, description=d)
    for n, d in [
        ("busca", "Texto livre (título, resumo, palavras-chave e corpo do PDF)"),
        ("titulo", "Parte do título"),
        ("autor", "Nome do autor"),
        ("orientador", "UUID ou nome do orientador"),
        ("curso", "UUID ou nome do curso"),
        ("ano_defesa", "Ano"),
        ("palavras_chave", "Lista separada por vírgula"),
        ("ordenar", "relevancia | recentes | titulo"),
    ]
]


@extend_schema_view(
    retrieve=extend_schema(parameters=[OpenApiParameter("id", OpenApiTypes.UUID, OpenApiParameter.PATH)]),
    download=extend_schema(parameters=[OpenApiParameter("id", OpenApiTypes.UUID, OpenApiParameter.PATH)]),
)
class MonografiaPublicaViewSet(_Publico, viewsets.ReadOnlyModelViewSet):
    serializer_class = DocumentoPublicoSerializer
    lookup_field = "monografia_id"
    lookup_url_kwarg = "pk"

    def get_queryset(self):
        qs = DocumentoIndexado.publicos.defer("texto_completo", "search_vector")
        p = self.request.query_params
        if p.get("titulo"):
            qs = qs.filter(titulo_norm__contains=normalizar(p["titulo"]))
        if p.get("autor"):
            qs = qs.filter(autor_norm__contains=normalizar(p["autor"]))
        if p.get("orientador"):
            oid = _uuid(p["orientador"])
            qs = (
                qs.filter(orientador_id=oid)
                if oid
                else qs.filter(orientador_norm__contains=normalizar(p["orientador"]))
            )
        if p.get("curso"):
            cid = _uuid(p["curso"])
            qs = qs.filter(curso_id=cid) if cid else qs.filter(curso_nome__icontains=p["curso"].strip())
        if p.get("ano_defesa", "").isdigit():
            qs = qs.filter(ano_defesa=int(p["ano_defesa"]))
        if p.get("palavras_chave"):
            termos = [normalizar(t) for t in p["palavras_chave"].split(",") if t.strip()]
            qs = qs.filter(palavras_chave_norm__overlap=termos)
        ordenar = p.get("ordenar", "relevancia")
        busca = (p.get("busca") or "").strip()
        if busca:
            consulta = SearchQuery(normalizar(busca), search_type="websearch", config=settings.FTS_CONFIG)
            qs = qs.filter(search_vector=consulta).annotate(
                relevancia=SearchRank(F("search_vector"), consulta),
                trecho=SearchHeadline(
                    "resumo",
                    SearchQuery(busca, search_type="websearch", config=settings.FTS_CONFIG),
                    config=settings.FTS_CONFIG,
                    start_sel="[[",
                    stop_sel="]]",
                    max_words=35,
                    min_words=15,
                ),
            )
            if ordenar == "relevancia":
                return qs.order_by("-relevancia", "-publicado_em")
        if ordenar == "titulo":
            return qs.order_by("titulo")
        return qs.order_by("-publicado_em")

    @extend_schema(parameters=FILTROS)
    def list(self, request, *args, **kwargs):
        dados, status_cache = obter_ou_calcular(
            request.query_params, lambda: super(MonografiaPublicaViewSet, self).list(request).data
        )
        resp = Response(dados)
        resp["X-Cache"] = status_cache
        return resp

    def retrieve(self, request, *args, **kwargs):
        doc = self.get_object()
        dados = self.get_serializer(doc).data
        try:
            dados["downloads"] = int(get_redis().get(f"downloads:{doc.monografia_id}") or 0)
        except redis.RedisError:
            dados["downloads"] = None  # contador é só informativo
        dados["download_url"] = f"/api/repositorio/monografias/{doc.monografia_id}/download/"
        return Response(dados)

    @extend_schema(responses={(200, "application/pdf"): bytes})
    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        doc = get_object_or_404(DocumentoIndexado.publicos, monografia_id=pk)
        caminho = Path(doc.arquivo_local or "")
        if not caminho.is_file():
            raise exceptions.NotFound("Arquivo indisponível.")
        # TODO: sem Redis o download dá 500 (cache da verificação de hash e contador ficam aqui).
        # A busca e o detalhe já seguem sem Redis; aqui daria para verificar o hash direto.
        r = get_redis()
        chave_ok = f"integridade_publica:{doc.monografia_id}"
        if not r.get(chave_ok):  # verificação de hash, cacheada por 1 h
            sha = hashlib.sha256()
            with caminho.open("rb") as f:
                for bloco in iter(lambda: f.read(1024 * 1024), b""):
                    sha.update(bloco)
            if sha.hexdigest() != doc.arquivo_sha256:
                raise exceptions.APIException("Falha na verificação de integridade do arquivo.")
            r.set(chave_ok, "1", ex=3600)
        r.incr(f"downloads:{doc.monografia_id}")
        resp = FileResponse(caminho.open("rb"), content_type="application/pdf", filename=f"{doc.monografia_id}.pdf")
        resp["X-Arquivo-SHA256"] = doc.arquivo_sha256
        return resp


class CursoPublicoSerializer(serializers.ModelSerializer):
    total_publicadas = serializers.IntegerField(read_only=True)

    class Meta:
        model = CursoRef
        fields = ["id", "nome", "codigo", "total_publicadas"]


class OrientadorPublicoSerializer(serializers.ModelSerializer):
    total_publicadas = serializers.IntegerField(read_only=True)

    class Meta:
        model = ProfessorRef
        fields = ["id", "nome", "departamento", "area_pesquisa", "total_publicadas"]


def _contagem(campo: str) -> dict:
    return dict(
        DocumentoIndexado.publicos.values_list(campo).annotate(n=Count("monografia_id")).values_list(campo, "n")
    )


class CursosPublicosView(_Publico, generics.ListAPIView):
    serializer_class = CursoPublicoSerializer
    pagination_class = None

    def get_queryset(self):
        return CursoRef.objects.all()

    def list(self, request, *args, **kwargs):
        cont = _contagem("curso_id")
        dados = [{**CursoPublicoSerializer(c).data, "total_publicadas": cont.get(c.id, 0)} for c in self.get_queryset()]
        return Response(dados)


class OrientadoresPublicosView(_Publico, generics.ListAPIView):
    serializer_class = OrientadorPublicoSerializer
    pagination_class = None

    def get_queryset(self):
        qs = ProfessorRef.objects.all()
        nome = self.request.query_params.get("nome")
        return qs.filter(Q(nome__icontains=nome)) if nome else qs

    def list(self, request, *args, **kwargs):
        cont = _contagem("orientador_id")
        dados = [
            {**OrientadorPublicoSerializer(p).data, "total_publicadas": cont.get(p.id, 0)} for p in self.get_queryset()
        ]
        return Response(dados)

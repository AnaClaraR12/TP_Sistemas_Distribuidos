import requests
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bancas import servicos
from apps.bancas.models import Avaliacao, Banca, MembroBanca, MonografiaRef
from apps.bancas.serializers import (
    AvaliacaoEntradaSerializer,
    AvaliacaoSerializer,
    BancaCriacaoSerializer,
    BancaEdicaoSerializer,
    BancaSerializer,
    MembroEntradaSerializer,
    MembroSerializer,
    MotivoSerializer,
    RespostaSerializer,
)
from tcc_common.api.exceptions import ErroNegocio
from tcc_common.audit.auditoria import registrar_auditoria
from tcc_common.audit.historico import HistoricoMixin
from tcc_common.auth.permissions import IsAutenticado
from tcc_common.cache.redis import verificar_rate_limit
from tcc_common.middleware.rede_institucional import ip_do_cliente


def _bancas_visiveis(u):
    qs = Banca.objects.prefetch_related("membros")
    if u.papel == "admin":
        return qs
    if u.papel == "aluno":
        return qs.filter(monografia_id__in=MonografiaRef.objects.filter(aluno_id=u.aluno_id).values("id"))
    filtro = qs.none()
    if u.professor_id:
        filtro = qs.filter(membros__professor_id=u.professor_id) | qs.filter(
            monografia_id__in=MonografiaRef.objects.filter(orientador_id=u.professor_id).values("id")
        )
    if u.papel == "coordenador":
        filtro = filtro | qs.filter(
            monografia_id__in=MonografiaRef.objects.filter(curso_id__in=u.curso_ids).values("id")
        )
    return filtro.distinct()


def _pode_ver(u, banca: Banca) -> bool:
    return _bancas_visiveis(u).filter(pk=banca.pk).exists()


def _exigir_gestor(u, banca: Banca) -> None:
    monografia = MonografiaRef.objects.filter(pk=banca.monografia_id).first()
    if monografia is None or not servicos.pode_gerir_banca(u, monografia):
        raise exceptions.PermissionDenied("Somente coordenador ou orientador gerenciam a banca.")


def _membro_do_usuario(u, banca: Banca) -> MembroBanca:
    membro = banca.membros.filter(professor_id=u.professor_id).first() if u.professor_id else None
    if membro is None:
        raise exceptions.PermissionDenied("Você não é membro desta banca.")
    return membro


def _stream_pdf(monografia_id) -> StreamingHttpResponse:
    """Faz streaming do PDF do monografias-service (HTTP interno com token de serviço)."""
    try:
        resp = requests.get(
            f"{settings.SERVICOS_URLS['monografias']}/internal/monografias/{monografia_id}/arquivo/",
            headers={"X-Service-Token": settings.SERVICE_TOKEN},
            stream=True,
            timeout=10,
        )
    except requests.RequestException as exc:
        raise ErroNegocio(
            "Serviço de monografias indisponível.", codigo="servico_indisponivel", status_code=503
        ) from exc
    if resp.status_code != 200:
        raise exceptions.NotFound("Arquivo não disponível.")
    r = StreamingHttpResponse(resp.iter_content(64 * 1024), content_type="application/pdf")
    r["Content-Disposition"] = f'inline; filename="{monografia_id}.pdf"'
    return r


class BancaViewSet(HistoricoMixin, viewsets.ModelViewSet):
    permission_classes = [IsAutenticado]
    serializer_class = BancaSerializer
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # geração do schema OpenAPI (sem usuário)
            return Banca.objects.none()
        qs = _bancas_visiveis(self.request.user)
        p = self.request.query_params
        if p.get("minhas") in ("1", "true") and self.request.user.professor_id:
            qs = qs.filter(membros__professor_id=self.request.user.professor_id)
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("monografia"):
            qs = qs.filter(monografia_id=p["monografia"])
        return qs

    def get_object(self) -> Banca:
        banca = get_object_or_404(Banca, pk=self.kwargs["pk"])
        if not _pode_ver(self.request.user, banca):
            raise exceptions.PermissionDenied("Você não tem acesso a esta banca.")
        return banca

    @extend_schema(request=BancaCriacaoSerializer, responses={201: BancaSerializer})
    def create(self, request, *args, **kwargs):
        if request.user.papel not in ("admin", "coordenador", "professor"):
            raise exceptions.PermissionDenied("Somente coordenador ou orientador agendam bancas.")
        s = BancaCriacaoSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        banca = servicos.criar_banca(s.validated_data, request.user, request)
        return Response(BancaSerializer(banca).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=BancaEdicaoSerializer, responses=BancaSerializer)
    def update(self, request, *args, **kwargs):
        banca = self.get_object()
        _exigir_gestor(request.user, banca)
        s = BancaEdicaoSerializer(data=request.data, partial=kwargs.get("partial", False))
        s.is_valid(raise_exception=True)
        banca = servicos.editar_banca(banca, s.validated_data, request.user, request)
        return Response(BancaSerializer(banca).data)

    def destroy(self, request, *args, **kwargs):
        banca = self.get_object()
        _exigir_gestor(request.user, banca)
        if banca.status not in (Banca.Status.CANCELADA, Banca.Status.EM_ORGANIZACAO):
            raise ErroNegocio(
                "Só é possível excluir bancas canceladas ou em organização.", codigo="exclusao_nao_permitida"
            )
        with transaction.atomic():
            pk = banca.pk
            banca.delete()
            registrar_auditoria("banca_excluida", "banca", pk, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses=BancaSerializer)
    @action(detail=True, methods=["post"])
    def agendar(self, request, pk=None):
        banca = self.get_object()
        banca = servicos.agendar(banca.pk, request.user, request)
        return Response(BancaSerializer(banca).data)

    @extend_schema(request=MotivoSerializer, responses=BancaSerializer)
    @action(detail=True, methods=["post"])
    def cancelar(self, request, pk=None):
        banca = self.get_object()
        _exigir_gestor(request.user, banca)
        s = MotivoSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(
            BancaSerializer(servicos.cancelar(banca, s.validated_data["motivo"], request.user, request)).data
        )

    @extend_schema(request=None, responses=BancaSerializer)
    @action(detail=True, methods=["post"], url_path="marcar-realizada")
    def marcar_realizada(self, request, pk=None):
        banca = self.get_object()
        if request.user.papel not in ("admin", "coordenador"):
            _exigir_gestor(request.user, banca)
        return Response(BancaSerializer(servicos.marcar_realizada(banca, request.user, request)).data)

    @extend_schema(request=MembroEntradaSerializer, responses={201: MembroSerializer})
    @action(detail=True, methods=["post"], url_path="membros")
    def adicionar_membro(self, request, pk=None):
        banca = self.get_object()
        _exigir_gestor(request.user, banca)
        if banca.status != Banca.Status.EM_ORGANIZACAO:
            raise ErroNegocio("Membros só podem ser alterados durante a organização.", codigo="banca_nao_editavel")
        s = MembroEntradaSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic():
            membro = servicos.adicionar_membro(
                banca,
                s.validated_data,
                MonografiaRef.objects.filter(pk=banca.monografia_id).first(),
                request.user,
                request,
            )
        return Response(MembroSerializer(membro).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["delete"], url_path=r"membros/(?P<membro_id>[0-9a-f-]{36})")
    def remover_membro(self, request, pk=None, membro_id=None):
        banca = self.get_object()
        _exigir_gestor(request.user, banca)
        if banca.status != Banca.Status.EM_ORGANIZACAO:
            raise ErroNegocio("Membros só podem ser alterados durante a organização.", codigo="banca_nao_editavel")
        membro = get_object_or_404(MembroBanca, pk=membro_id, banca=banca)
        if membro.funcao == MembroBanca.Funcao.ORIENTADOR:
            raise ErroNegocio("O orientador não pode ser removido.", codigo="orientador_obrigatorio")
        with transaction.atomic():
            membro.delete()
            registrar_auditoria(
                "membro_removido", "banca", banca.id, request=request, detalhes={"membro": membro.email}
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=RespostaSerializer, responses=MembroSerializer)
    @action(detail=True, methods=["post"], url_path=r"membros/(?P<membro_id>[0-9a-f-]{36})/confirmar")
    def confirmar(self, request, pk=None, membro_id=None):
        banca = self.get_object()
        membro = get_object_or_404(MembroBanca, pk=membro_id, banca=banca)
        if not request.user.professor_id or str(membro.professor_id) != request.user.professor_id:
            raise exceptions.PermissionDenied("Somente o próprio membro confirma a disponibilidade.")
        s = RespostaSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(
            MembroSerializer(
                servicos.responder_convite(membro, s.validated_data["resposta"], request.user, request)
            ).data
        )

    @extend_schema(methods=["GET"], responses=AvaliacaoSerializer(many=True), operation_id="bancas_avaliacoes_listar")
    @extend_schema(
        methods=["POST"],
        request=AvaliacaoEntradaSerializer,
        responses={201: AvaliacaoSerializer},
        operation_id="bancas_avaliacoes_criar",
    )
    @action(detail=True, methods=["get", "post"], url_path="avaliacoes")
    def avaliacoes(self, request, pk=None):
        banca = self.get_object()
        if request.method == "GET":
            qs = banca.avaliacoes.select_related("membro")
            if request.user.papel == "aluno" and banca.resultado_calculado_em is None:
                qs = qs.none()  # aluno só vê pareceres após o fechamento
            return Response(AvaliacaoSerializer(qs, many=True).data)
        membro = _membro_do_usuario(request.user, banca)
        s = AvaliacaoEntradaSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        av = servicos.registrar_avaliacao(banca, membro, s.validated_data, request.user, request)
        return Response(AvaliacaoSerializer(av).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="pdf")
    def pdf(self, request, pk=None):
        banca = self.get_object()
        if request.user.papel not in ("admin", "coordenador"):
            _membro_do_usuario(request.user, banca)
        return _stream_pdf(banca.monografia_id)


class AvaliacaoViewSet(
    HistoricoMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """/api/avaliacoes/ e /api/bancas/{banca}/avaliacoes/{id}/

    Editar: só o próprio avaliador. Excluir: o próprio avaliador ou o admin.
    As duas coisas só valem antes de o resultado da banca ser fechado.
    """

    permission_classes = [IsAutenticado]
    serializer_class = AvaliacaoSerializer
    http_method_names = ["get", "patch", "put", "delete", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Avaliacao.objects.none()
        u = self.request.user
        qs = Avaliacao.objects.select_related("membro", "banca")
        if "banca_pk" in self.kwargs:
            qs = qs.filter(banca_id=self.kwargs["banca_pk"])
        if u.papel in ("admin",):
            return qs
        if u.papel == "coordenador":
            return qs.filter(banca__in=_bancas_visiveis(u))
        if u.professor_id:
            return qs.filter(membro__professor_id=u.professor_id)
        return qs.none()

    @extend_schema(request=AvaliacaoEntradaSerializer, responses=AvaliacaoSerializer)
    def update(self, request, *args, **kwargs):
        av = self.get_object()
        if not request.user.professor_id or str(av.membro.professor_id) != request.user.professor_id:
            raise exceptions.PermissionDenied("Somente o próprio avaliador edita a avaliação.")
        s = AvaliacaoEntradaSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        return Response(
            AvaliacaoSerializer(servicos.editar_avaliacao(av, s.validated_data, request.user, request)).data
        )

    def destroy(self, request, *args, **kwargs):
        av = self.get_object()
        u = request.user
        e_o_avaliador = bool(u.professor_id) and str(av.membro.professor_id) == u.professor_id
        if not (e_o_avaliador or u.papel == "admin"):
            raise exceptions.PermissionDenied("Somente o próprio avaliador ou o admin excluem a avaliação.")
        servicos.excluir_avaliacao(av, u, request)
        return Response(status=status.HTTP_204_NO_CONTENT)


# Membro externo (sem login, header X-Banca-Token)
TOKEN_HEADER = OpenApiParameter("X-Banca-Token", str, OpenApiParameter.HEADER, required=True)


class _ExternoBase(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]  # autenticação própria por token de escopo restrito

    def membro(self, request) -> MembroBanca:
        ip = ip_do_cliente(request)
        ok, retry = verificar_rate_limit(f"rl:ip:{ip}:externo", settings.EXTERNO_RATE_LIMIT_POR_MIN, 60)
        if not ok:
            raise ErroNegocio(
                "Muitas requisições.",
                codigo="limite_de_requisicoes",
                status_code=429,
                headers={"Retry-After": str(retry)},
            )
        membro = servicos.membro_por_token(request.headers.get("X-Banca-Token", ""))
        registrar_auditoria(
            "token_externo_usado",
            "membro_banca",
            membro.id,
            request=request,
            detalhes={"rota": request.path, "banca_id": str(membro.banca_id)},
        )
        return membro


class ExternoMinhaBancaView(_ExternoBase):
    @extend_schema(parameters=[TOKEN_HEADER], responses={200: dict})
    def get(self, request):
        m = self.membro(request)
        b = m.banca
        monografia = MonografiaRef.objects.filter(pk=b.monografia_id).first()
        assinatura = signing.TimestampSigner(salt="pdf-externo").sign(f"{m.id}:{b.monografia_id}")
        avaliacao = m.avaliacoes.first()
        return Response(
            {
                "banca": {
                    "id": str(b.id),
                    "data_hora_inicio": b.data_hora_inicio,
                    "duracao_minutos": b.duracao_minutos,
                    "local": b.local,
                    "link": b.link,
                    "status": b.status,
                    "resultado_fechado": b.resultado_calculado_em is not None,
                },
                "monografia": {"titulo": monografia.titulo if monografia else ""},
                "membro": {"id": str(m.id), "nome": m.nome, "confirmacao": m.confirmacao, "funcao": m.funcao},
                "minha_avaliacao": AvaliacaoSerializer(avaliacao).data if avaliacao else None,
                "pdf_url": f"/api/bancas/externo/arquivo/?assinatura={assinatura}",
                "pdf_url_expira_em_s": settings.URL_ASSINADA_TTL_S,
            }
        )


class ExternoConfirmarView(_ExternoBase):
    @extend_schema(parameters=[TOKEN_HEADER], request=RespostaSerializer, responses=MembroSerializer)
    def post(self, request):
        m = self.membro(request)
        s = RespostaSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(
            MembroSerializer(servicos.responder_convite(m, s.validated_data["resposta"], request=request)).data
        )


class ExternoAvaliacaoView(_ExternoBase):
    @extend_schema(parameters=[TOKEN_HEADER], request=AvaliacaoEntradaSerializer, responses=AvaliacaoSerializer)
    def post(self, request):
        m = self.membro(request)
        s = AvaliacaoEntradaSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        av = servicos.registrar_avaliacao(m.banca, m, s.validated_data, request=request)
        return Response(AvaliacaoSerializer(av).data, status=status.HTTP_201_CREATED)

    @extend_schema(parameters=[TOKEN_HEADER], request=AvaliacaoEntradaSerializer, responses=AvaliacaoSerializer)
    def patch(self, request):
        m = self.membro(request)
        av = m.avaliacoes.first()
        if av is None:
            raise exceptions.NotFound("Avaliação ainda não registrada.")
        s = AvaliacaoEntradaSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        return Response(AvaliacaoSerializer(servicos.editar_avaliacao(av, s.validated_data, request=request)).data)

    @extend_schema(parameters=[TOKEN_HEADER], request=None, responses={204: None})
    def delete(self, request):
        m = self.membro(request)
        av = m.avaliacoes.first()
        if av is None:
            raise exceptions.NotFound("Avaliação ainda não registrada.")
        servicos.excluir_avaliacao(av, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExternoArquivoView(APIView):
    """PDF via URL assinada de curta duração (gerada em minha-banca)."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter("assinatura", str, required=True)], responses={(200, "application/pdf"): bytes}
    )
    def get(self, request):
        try:
            valor = signing.TimestampSigner(salt="pdf-externo").unsign(
                request.query_params.get("assinatura", ""), max_age=settings.URL_ASSINADA_TTL_S
            )
        except signing.BadSignature as exc:
            raise ErroNegocio("Link expirado ou inválido.", codigo="assinatura_invalida", status_code=403) from exc
        membro_id, monografia_id = valor.split(":")
        membro = get_object_or_404(MembroBanca, pk=membro_id)
        if membro.token_revogado or str(membro.banca.monografia_id) != monografia_id:
            raise ErroNegocio("Acesso revogado.", codigo="token_revogado", status_code=403)
        return _stream_pdf(monografia_id)

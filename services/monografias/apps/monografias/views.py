"""API restrita de monografias (/api/monografias/) e endpoint interno de arquivo."""

from __future__ import annotations

from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.monografias import servicos
from apps.monografias.estados import Status
from apps.monografias.filtros import MonografiaFiltro
from apps.monografias.models import AlunoRef, DocumentoComplementar, Monografia
from apps.monografias.serializers import (
    ArquivoUploadSerializer,
    DocumentoSerializer,
    DocumentoUploadSerializer,
    MonografiaCriacaoAdminSerializer,
    MonografiaSerializer,
    MotivoSerializer,
)
from tcc_common.api.exceptions import ErroNegocio
from tcc_common.audit.auditoria import registrar_auditoria
from tcc_common.audit.historico import HistoricoMixin
from tcc_common.auth.permissions import IsAutenticado, IsServicoInterno


def _s(v) -> str:
    return str(v) if v else ""


def pode_ver(u, m: Monografia) -> bool:
    if u.papel == "admin":
        return True
    if u.aluno_id and _s(m.aluno_id) == u.aluno_id:
        return True
    if u.professor_id and _s(m.orientador_id) == u.professor_id:
        return True
    return u.papel == "coordenador" and _s(m.curso_id) in set(u.curso_ids)


def eh_dono(u, m: Monografia) -> bool:
    return u.papel == "admin" or (bool(u.aluno_id) and _s(m.aluno_id) == u.aluno_id)


def eh_orientador(u, m: Monografia) -> bool:
    return u.papel == "admin" or (bool(u.professor_id) and _s(m.orientador_id) == u.professor_id)


def eh_coordenador_do_curso(u, m: Monografia) -> bool:
    return u.papel == "admin" or (u.papel == "coordenador" and _s(m.curso_id) in set(u.curso_ids))


def exigir(condicao: bool, mensagem: str = "Você não tem permissão para esta ação.") -> None:
    if not condicao:
        raise exceptions.PermissionDenied(mensagem)


class MonografiaViewSet(HistoricoMixin, viewsets.ModelViewSet):
    permission_classes = [IsAutenticado]
    serializer_class = MonografiaSerializer
    filterset_class = MonografiaFiltro
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = Monografia.objects.prefetch_related("documentos")
        if getattr(self, "swagger_fake_view", False):  # geração do schema OpenAPI (sem usuário)
            return qs.none()
        u = self.request.user
        if u.papel == "admin":
            return qs
        if u.papel == "aluno":
            return qs.filter(aluno_id=u.aluno_id)
        filtro = qs.filter(orientador_id=u.professor_id) if u.professor_id else qs.none()
        if u.papel == "coordenador":
            filtro = filtro | qs.filter(curso_id__in=u.curso_ids)
        return filtro.distinct()

    def get_object(self) -> Monografia:
        """Busca sem escopo e responde 403 (não 404) quando o usuário não tem acesso."""
        obj = get_object_or_404(Monografia, pk=self.kwargs["pk"])
        exigir(pode_ver(self.request.user, obj), "Você não tem acesso a esta monografia.")
        return obj

    def get_serializer_class(self):
        if self.action == "create" and getattr(self.request.user, "papel", None) == "admin":
            return MonografiaCriacaoAdminSerializer
        return super().get_serializer_class()

    # --- CRUD ---
    def perform_create(self, serializer):
        u = self.request.user
        exigir(u.papel in ("aluno", "admin"), "Somente alunos criam monografias.")
        aluno_id = serializer.validated_data.get("aluno_id") if u.papel == "admin" else u.aluno_id
        if not aluno_id:
            raise ErroNegocio("Usuário sem vínculo de aluno.", codigo="sem_vinculo_aluno", status_code=400)
        ref = AlunoRef.objects.filter(pk=aluno_id).first()
        curso_id = ref.curso_id if ref else (u.curso_ids[0] if u.curso_ids else None)
        orientador = serializer.validated_data.get("orientador_id") or (ref.orientador_id if ref else None)
        with transaction.atomic():
            m = serializer.save(aluno_id=aluno_id, curso_id=curso_id, orientador_id=orientador)
            registrar_auditoria("criacao", "monografia", m.id, request=self.request)

    def perform_update(self, serializer):
        m = serializer.instance
        exigir(eh_dono(self.request.user, m), "Somente o autor pode editar a monografia.")
        if m.status != Status.RASCUNHO:
            raise ErroNegocio("Só é possível editar monografias em rascunho.", codigo="edicao_nao_permitida")
        with transaction.atomic():
            serializer.save()
            registrar_auditoria(
                "alteracao",
                "monografia",
                m.id,
                request=self.request,
                detalhes={"campos": sorted(serializer.validated_data)},
            )

    def perform_destroy(self, m: Monografia):
        u = self.request.user
        if m.status == Status.PUBLICADA:
            raise ErroNegocio("Monografias publicadas não podem ser excluídas.", codigo="monografia_publicada_imutavel")
        dono_rascunho = u.papel == "aluno" and eh_dono(u, m) and m.status == Status.RASCUNHO
        exigir(dono_rascunho or eh_coordenador_do_curso(u, m), "Você não pode excluir esta monografia.")
        arquivos = [m.arquivo.name] if m.arquivo else []
        arquivos += [d.arquivo.name for d in m.documentos.all()]
        with transaction.atomic():
            pk = m.pk
            m.delete()
            from tcc_common.events.outbox import registrar_evento

            registrar_evento("monografia.excluida", {"id": pk})
            registrar_auditoria("exclusao", "monografia", pk, request=self.request)
        from django.core.files.storage import default_storage

        for nome in arquivos:
            transaction.on_commit(lambda n=nome: default_storage.delete(n))

    # --- ações de domínio ---
    @extend_schema(request={"multipart/form-data": ArquivoUploadSerializer}, responses=MonografiaSerializer)
    @action(detail=True, methods=["post"], url_path="arquivo", parser_classes=[MultiPartParser])
    def arquivo(self, request, pk=None):
        m = self.get_object()
        exigir(eh_dono(request.user, m), "Somente o autor envia o arquivo.")
        arquivo = request.FILES.get("arquivo")
        if arquivo is None:
            raise ErroNegocio("Envie o PDF no campo 'arquivo'.", codigo="arquivo_ausente", status_code=400)
        resultado = servicos.processar_upload(m, arquivo, request.user, request)
        codigo = status.HTTP_200_OK if resultado.idempotente else status.HTTP_201_CREATED
        return Response(MonografiaSerializer(resultado.monografia).data, status=codigo)

    @extend_schema(request=None, responses={202: MonografiaSerializer})
    @action(detail=True, methods=["post"], url_path="submeter")
    def submeter(self, request, pk=None):
        m = self.get_object()
        exigir(eh_dono(request.user, m), "Somente o autor submete a monografia.")
        servicos.submeter(m, request.user, request)
        return Response(MonografiaSerializer(m).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(request=None, responses=MonografiaSerializer)
    @action(detail=True, methods=["post"], url_path="aprovar-orientador")
    def aprovar_orientador(self, request, pk=None):
        m = self.get_object()
        exigir(eh_orientador(request.user, m), "Somente o orientador pode aprovar.")
        with transaction.atomic():
            m.aprovar_orientador()
            registrar_auditoria("aprovacao_orientador", "monografia", m.id, request=request)
        return Response(MonografiaSerializer(m).data)

    @extend_schema(request=MotivoSerializer, responses=MonografiaSerializer)
    @action(detail=True, methods=["post"], url_path="rejeitar-orientador")
    def rejeitar_orientador(self, request, pk=None):
        m = self.get_object()
        exigir(eh_orientador(request.user, m), "Somente o orientador pode rejeitar.")
        s = MotivoSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic():
            m.rejeitar_orientador(s.validated_data["motivo"])
            registrar_auditoria(
                "rejeicao_orientador",
                "monografia",
                m.id,
                request=request,
                detalhes={"motivo": s.validated_data["motivo"]},
            )
        return Response(MonografiaSerializer(m).data)

    @extend_schema(request=None, responses={200: dict})
    @action(detail=True, methods=["post"], url_path="verificar-integridade")
    def verificar_integridade(self, request, pk=None):
        m = self.get_object()
        return Response(servicos.verificar_integridade(m, request.user, request))

    @extend_schema(request=None, responses=MonografiaSerializer)
    @action(detail=True, methods=["post"], url_path="validar-correcao")
    def validar_correcao(self, request, pk=None):
        m = self.get_object()
        exigir(eh_orientador(request.user, m), "Somente o orientador valida a versão corrigida.")
        servicos.validar_correcao(m, request.user, request)
        return Response(MonografiaSerializer(m).data)

    @extend_schema(request={"multipart/form-data": DocumentoUploadSerializer}, responses=DocumentoSerializer)
    @action(detail=True, methods=["get", "post"], url_path="documentos", parser_classes=[MultiPartParser, JSONParser])
    def documentos(self, request, pk=None):
        m = self.get_object()
        if request.method == "GET":
            return Response(DocumentoSerializer(m.documentos.all(), many=True).data)
        s = DocumentoUploadSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        tipo = s.validated_data["tipo"]
        u = request.user
        papeis = servicos.QUEM_ENVIA[tipo]
        permitido = (
            u.papel == "admin"
            or ("aluno" in papeis and eh_dono(u, m))
            or ("orientador" in papeis and eh_orientador(u, m))
            or ("coordenador" in papeis and eh_coordenador_do_curso(u, m))
        )
        exigir(permitido, "Você não pode enviar este tipo de documento.")
        doc = servicos.enviar_documento(m, tipo, s.validated_data["arquivo"], u, request)
        return Response(DocumentoSerializer(doc).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=DocumentoSerializer)
    @action(detail=True, methods=["post"], url_path=r"documentos/(?P<doc_id>[0-9a-f-]{36})/validar-assinatura")
    def validar_assinatura(self, request, pk=None, doc_id=None):
        m = self.get_object()
        exigir(eh_coordenador_do_curso(request.user, m), "Somente coordenador/admin valida o termo.")
        doc = get_object_or_404(DocumentoComplementar, pk=doc_id, monografia=m)
        servicos.validar_assinatura(doc, request.user, request)
        return Response(DocumentoSerializer(doc).data)

    @extend_schema(responses={200: None})
    @action(detail=True, methods=["get"], url_path="arquivo/download")
    def download(self, request, pk=None):
        m = self.get_object()
        if not m.arquivo:
            raise exceptions.NotFound("Monografia sem arquivo.")
        return FileResponse(
            m.arquivo.open("rb"), content_type="application/pdf", as_attachment=False, filename=f"{m.id}.pdf"
        )


@extend_schema(exclude=True)  # rota interna (serviço-a-serviço), fora do gateway
class ArquivoInternoView(APIView):
    """GET /internal/monografias/{id}/arquivo/ — streaming do PDF para outros serviços."""

    authentication_classes: list = []
    permission_classes = [IsServicoInterno]

    def get(self, request, pk):
        m = get_object_or_404(Monografia, pk=pk)
        if not m.arquivo:
            raise exceptions.NotFound("Monografia sem arquivo.")
        resp = FileResponse(m.arquivo.open("rb"), content_type="application/pdf")
        resp["X-Arquivo-SHA256"] = m.arquivo_sha256 or ""
        return resp


@extend_schema(exclude=True)
class MonografiaInternaView(APIView):
    """GET /internal/monografias/{id}/ — metadados para o bancas-service (fallback do read model)."""

    authentication_classes: list = []
    permission_classes = [IsServicoInterno]

    def get(self, request, pk):
        m = get_object_or_404(Monografia, pk=pk)
        return Response({k: (str(v) if v is not None else None) for k, v in m.payload_base().items()})

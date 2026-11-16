from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.signals import user_logged_in
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.contas.backends import esta_bloqueado, tempo_restante
from apps.contas.dashboard import configuracao_dashboard
from apps.contas.serializers import (
    LoginSerializer,
    LogoutSerializer,
    MeSerializer,
    RefreshSerializer,
    UsuarioAdminSerializer,
)
from apps.contas.tokens import emitir_tokens, jwks
from tcc_common.api.exceptions import ErroNegocio
from tcc_common.audit.auditoria import AuditoriaViewSetMixin
from tcc_common.auth.jwt import TokenInvalido, decodificar_token, revogar_jti
from tcc_common.auth.permissions import IsAdmin, IsAutenticado

User = get_user_model()


class TokenView(APIView):
    """POST e-mail + senha -> access (15 min) + refresh (7 dias), RS256."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(request=LoginSerializer, responses={200: dict})
    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        email = s.validated_data["email"].lower()
        if esta_bloqueado(email):
            raise ErroNegocio(
                "Conta temporariamente bloqueada por excesso de tentativas. Tente mais tarde.",
                codigo="conta_bloqueada",
                status_code=429,
                headers={"Retry-After": str(tempo_restante(email) or 1)},
            )
        user = authenticate(request, email=email, password=s.validated_data["password"])
        if user is None or not user.is_active:
            raise ErroNegocio("E-mail ou senha inválidos.", codigo="credenciais_invalidas", status_code=401)
        user_logged_in.send(sender=user.__class__, request=request, user=user)
        return Response(emitir_tokens(user))


class RefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(request=RefreshSerializer, responses={200: dict})
    def post(self, request):
        s = RefreshSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            claims = decodificar_token(s.validated_data["refresh"], tipo="refresh")
        except TokenInvalido as exc:
            raise ErroNegocio(str(exc), codigo="token_invalido", status_code=401) from exc
        user = User.objects.filter(pk=claims["sub"], is_active=True).first()
        if user is None:
            raise ErroNegocio("Usuário inativo.", codigo="token_invalido", status_code=401)
        revogar_jti(claims["jti"], claims["exp"])  # rotação do refresh
        return Response(emitir_tokens(user))


class LogoutView(APIView):
    """Revoga o access atual (e o refresh, se enviado) até expirarem."""

    permission_classes = [IsAutenticado]

    @extend_schema(request=LogoutSerializer, responses={204: None})
    def post(self, request):
        revogar_jti(request.auth["jti"], request.auth["exp"])
        refresh = (request.data or {}).get("refresh")
        if refresh:
            try:
                c = decodificar_token(refresh, tipo="refresh")
                if c["sub"] == request.auth["sub"]:
                    revogar_jti(c["jti"], c["exp"])
            except TokenInvalido:
                pass
        from tcc_common.audit.auditoria import registrar_auditoria

        registrar_auditoria("logout", "usuario", request.user.id, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAutenticado]

    @extend_schema(responses=MeSerializer)
    def get(self, request):
        user = User.objects.select_related("aluno__curso", "aluno__orientador_atual", "professor").get(
            pk=request.user.id
        )
        return Response(MeSerializer(user).data)


class DashboardConfigView(APIView):
    permission_classes = [IsAutenticado]

    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response(configuracao_dashboard(request.user.papel))


@require_GET
def jwks_view(request):
    resp = JsonResponse(jwks())
    resp["Cache-Control"] = "public, max-age=300"
    return resp


class UsuarioAdminViewSet(
    AuditoriaViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Gestão de usuários (somente admin, somente rede institucional — /api/auth/admin/)."""

    permission_classes = [IsAdmin]
    serializer_class = UsuarioAdminSerializer
    queryset = User.objects.all().order_by("email")
    filterset_fields = ["papel", "is_active"]
    auditoria_recurso = "usuario"
    http_method_names = ["get", "patch", "head", "options"]

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework import authentication, exceptions

from tcc_common import usuario_atual
from tcc_common.auth.jwt import TokenInvalido, decodificar_token
from tcc_common.auth.usuario import UsuarioToken


class JWTAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header:
            return None
        partes = header.split()
        if len(partes) != 2 or partes[0] != self.keyword:
            raise exceptions.AuthenticationFailed("Cabeçalho Authorization malformado.")
        try:
            claims = decodificar_token(partes[1], tipo="access")
        except TokenInvalido as exc:
            raise exceptions.AuthenticationFailed(str(exc)) from exc
        usuario = UsuarioToken.de_claims(claims)
        usuario_atual.set(usuario)
        return usuario, claims

    def authenticate_header(self, request):
        return self.keyword


class JWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "tcc_common.auth.authentication.JWTAuthentication"
    name = "BearerJWT"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}

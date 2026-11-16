from dataclasses import dataclass, field


@dataclass(frozen=True)
class UsuarioToken:
    """Usuário montado só com os claims do JWT: os serviços não têm tabela de usuários."""

    id: str
    email: str
    papel: str
    nome: str = ""
    aluno_id: str | None = None
    professor_id: str | None = None
    curso_ids: tuple[str, ...] = field(default_factory=tuple)
    jti: str = ""
    exp: int = 0

    # o DRF e o Django consultam estes atributos
    is_authenticated = True
    is_anonymous = False
    is_active = True

    @property
    def pk(self):
        return self.id

    @classmethod
    def de_claims(cls, claims):
        return cls(
            id=str(claims["sub"]),
            email=claims.get("email", ""),
            papel=claims.get("papel", ""),
            nome=claims.get("nome", ""),
            aluno_id=claims.get("aluno_id"),
            professor_id=claims.get("professor_id"),
            curso_ids=tuple(claims.get("curso_ids") or ()),
            jti=claims.get("jti", ""),
            exp=int(claims.get("exp", 0)),
        )

    def __str__(self):
        return f"{self.email} ({self.papel})"

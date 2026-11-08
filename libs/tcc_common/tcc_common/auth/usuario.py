"""Representação do usuário autenticado a partir dos claims do JWT (sem acesso ao banco)."""

from __future__ import annotations

from dataclasses import dataclass, field

PAPEIS = ("admin", "coordenador", "professor", "aluno")


@dataclass(frozen=True)
class UsuarioToken:
    id: str
    email: str
    papel: str
    nome: str = ""
    aluno_id: str | None = None
    professor_id: str | None = None
    curso_ids: tuple[str, ...] = field(default_factory=tuple)
    jti: str = ""
    exp: int = 0

    is_authenticated = True
    is_anonymous = False
    is_active = True

    @property
    def pk(self) -> str:
        return self.id

    @property
    def is_admin(self) -> bool:
        return self.papel == "admin"

    @property
    def is_coordenador(self) -> bool:
        return self.papel == "coordenador"

    def tem_papel(self, *papeis: str) -> bool:
        return self.papel in papeis

    @classmethod
    def de_claims(cls, claims: dict) -> UsuarioToken:
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

    def __str__(self) -> str:
        return f"{self.email} ({self.papel})"

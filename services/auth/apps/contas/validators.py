import re

from django.core.exceptions import ValidationError


class ComplexidadeSenhaValidator:
    regras = (
        (r"[A-Z]", "uma letra maiúscula"),
        (r"[a-z]", "uma letra minúscula"),
        (r"\d", "um dígito"),
        (r"[^A-Za-z0-9]", "um símbolo"),
    )

    def validate(self, password: str, user=None) -> None:
        faltando = [desc for padrao, desc in self.regras if not re.search(padrao, password or "")]
        if faltando:
            raise ValidationError(
                "A senha deve conter pelo menos: " + ", ".join(faltando) + ".",
                code="senha_fraca",
            )

    def get_help_text(self) -> str:
        return "A senha deve conter letra maiúscula, letra minúscula, dígito e símbolo."

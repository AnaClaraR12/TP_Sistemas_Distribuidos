"""DEMO: define a mesma senha para os usuários de um domínio de demonstração.

Recusa-se a rodar sem --confirmar e só altera e-mails do domínio informado (padrão: demo.tcc.br),
para nunca afetar contas reais.
"""

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Define a senha de demonstração para usuários @<dominio> (uso exclusivo em ambiente de demo)."

    def add_arguments(self, parser):
        parser.add_argument("--dominio", default="demo.tcc.br")
        parser.add_argument("--senha", default=os.environ.get("SEED_SENHA_PADRAO"))
        parser.add_argument("--confirmar", action="store_true")

    def handle(self, *args, dominio, senha, confirmar, **opts):
        if not confirmar:
            raise CommandError("Use --confirmar (comando destinado apenas a ambientes de demonstração).")
        if not senha:
            raise CommandError("Informe --senha ou SEED_SENHA_PADRAO.")
        validate_password(senha)
        n = 0
        for u in get_user_model().objects.filter(email__iendswith="@" + dominio):
            u.set_password(senha)
            u.save(update_fields=["password"])
            n += 1
        self.stdout.write(self.style.SUCCESS(f"{n} senhas de demonstração definidas."))

"""Cria (ou atualiza) o administrador inicial. Uso: manage.py garantir_admin --email X [--senha Y]."""

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Garante a existência do usuário administrador (senha via --senha ou ADMIN_SENHA)."

    def add_arguments(self, parser):
        parser.add_argument("--email", default=os.environ.get("ADMIN_EMAIL", "admin@tcc.local"))
        parser.add_argument("--senha", default=os.environ.get("ADMIN_SENHA") or os.environ.get("SEED_SENHA_PADRAO"))
        parser.add_argument("--nome", default="Administrador")

    def handle(self, *args, email, senha, nome, **opts):
        if not senha:
            raise CommandError("Informe --senha ou defina ADMIN_SENHA/SEED_SENHA_PADRAO.")
        validate_password(senha)
        User = get_user_model()
        user, criado = User.objects.get_or_create(email=email.lower(), defaults={"nome": nome, "papel": "admin"})
        user.papel = "admin"
        user.is_staff = user.is_superuser = True
        user.set_password(senha)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Admin {'criado' if criado else 'atualizado'}: {user.email}"))

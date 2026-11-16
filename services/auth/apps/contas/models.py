import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from tcc_common.audit.historico import Historico


class Papel(models.TextChoices):
    ADMIN = "admin", "Administrador"
    COORDENADOR = "coordenador", "Coordenador de curso"
    PROFESSOR = "professor", "Professor/Orientador"
    ALUNO = "aluno", "Aluno"


#: papel -> nome do grupo Django criado pela data migration
GRUPO_POR_PAPEL = {
    Papel.ADMIN: "Administradores",
    Papel.COORDENADOR: "Coordenadores",
    Papel.PROFESSOR: "Professores",
    Papel.ALUNO: "Alunos",
}


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _criar(self, email: str, password: str | None, **extra) -> "User":
        if not email:
            raise ValueError("O e-mail é obrigatório.")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra) -> "User":
        extra.setdefault("papel", Papel.ALUNO)
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._criar(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra) -> "User":
        extra.update(papel=Papel.ADMIN, is_staff=True, is_superuser=True)
        return self._criar(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField("e-mail", unique=True)
    nome = models.CharField(max_length=150, blank=True)
    papel = models.CharField(max_length=20, choices=Papel.choices, default=Papel.ALUNO, db_index=True)
    is_active = models.BooleanField("ativo", default=True)
    is_staff = models.BooleanField(default=False)
    ultimo_login_ip = models.GenericIPAddressField(null=True, blank=True)
    date_joined = models.DateTimeField(default=timezone.now)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    history = Historico(excluded_fields=["password", "last_login"])

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"
        ordering = ["email"]

    def __str__(self) -> str:
        return self.email

    def save(self, *args, **kwargs):
        self.email = (self.email or "").lower()
        if self.papel == Papel.ADMIN:
            self.is_staff = True
        super().save(*args, **kwargs)

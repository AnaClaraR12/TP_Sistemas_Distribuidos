from django.apps import AppConfig


class ContasConfig(AppConfig):
    name = "apps.contas"
    label = "contas"
    verbose_name = "Contas de usuário"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from apps.contas import signals  # noqa: F401

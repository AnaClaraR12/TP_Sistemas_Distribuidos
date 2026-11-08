from django.apps import AppConfig


class EventsConfig(AppConfig):
    name = "tcc_common.events"
    label = "events"
    verbose_name = "Eventos (outbox / idempotência)"
    default_auto_field = "django.db.models.BigAutoField"

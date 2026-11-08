import os

os.environ.setdefault("DJANGO_SECRET_KEY", "chave-de-teste")
os.environ.setdefault("REDIS_URL", "fakeredis://")

from .base import *  # noqa: E402,F401,F403

DEBUG = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
READY_CHECK_RABBITMQ = False
LOGGING = {"version": 1, "disable_existing_loggers": False}

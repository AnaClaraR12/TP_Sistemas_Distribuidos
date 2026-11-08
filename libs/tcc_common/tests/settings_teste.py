import os

os.environ.setdefault("DJANGO_SECRET_KEY", "teste")
os.environ.setdefault("REDIS_URL", "fakeredis://")

from tcc_common.settings_base import construir  # noqa: E402

globals().update(construir(servico="common", apps=[]))
ROOT_URLCONF = "tests.urls_teste"
LOGGING = {"version": 1, "disable_existing_loggers": False}

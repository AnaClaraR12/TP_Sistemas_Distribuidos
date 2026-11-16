from pathlib import Path

from tcc_common.settings_base import construir, env

BASE_DIR = Path(__file__).resolve().parents[2]
globals().update(construir(servico="notificacoes", base_dir=BASE_DIR, apps=["apps.notificacoes"]))

EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="mailhog")
EMAIL_PORT = env.int("EMAIL_PORT", default=1025)
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="TCC <nao-responda@tcc.local>")

NOTIFICACOES_ADMIN_EMAILS = env.list("NOTIFICACOES_ADMIN_EMAILS", default=["admin@tcc.local"])
NOTIFICACAO_TENTATIVAS = env.int("NOTIFICACAO_TENTATIVAS", default=3)
NOTIFICACAO_BACKOFF_S = env.float("NOTIFICACAO_BACKOFF_S", default=1.0)  # 1 s, 2 s, 4 s ...

EVENT_HANDLERS = "apps.notificacoes.eventos.HANDLERS"

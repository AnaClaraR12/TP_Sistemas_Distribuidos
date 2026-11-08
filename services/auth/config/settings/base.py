"""Settings do auth-service."""

from pathlib import Path

from tcc_common.settings_base import construir, env

BASE_DIR = Path(__file__).resolve().parents[2]
globals().update(
    construir(
        servico="auth",
        porta=8001,
        base_dir=BASE_DIR,
        apps=[
            "django.contrib.admin",
            "django.contrib.sessions",
            "django.contrib.messages",
            "allauth",
            "allauth.account",
            "apps.contas",
            "apps.academico",
            "apps.auditoria",
        ],
    )
)

MIDDLEWARE = [  # noqa: F405
    *MIDDLEWARE[:4],  # noqa: F405  security, whitenoise, cors, request-id
    "django.contrib.sessions.middleware.SessionMiddleware",
    *MIDDLEWARE[4:],  # noqa: F405  rede institucional, common, clickjacking
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]
TEMPLATES[0]["OPTIONS"]["context_processors"] += [  # noqa: F405
    "django.contrib.messages.context_processors.messages",
]

AUTH_USER_MODEL = "contas.User"

# --- Senhas: Argon2 + política forte ---
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        "OPTIONS": {"user_attributes": ("email", "nome")},
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "apps.contas.validators.ComplexidadeSenhaValidator"},
]

# --- Bloqueio por tentativas (Redis login_falhas:<email>) ---
LOGIN_MAX_FALHAS = env.int("LOGIN_MAX_FALHAS", default=5)
LOGIN_JANELA_S = env.int("LOGIN_JANELA_S", default=900)

AUTHENTICATION_BACKENDS = [
    "apps.contas.backends.BloqueioPorTentativasBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# --- Sessões no Redis (Django Admin / allauth) ---
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "sessoes"

# --- django-allauth ---
ACCOUNT_ADAPTER = "apps.contas.adapters.ContaAdapter"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_EMAIL_VERIFICATION = env("ACCOUNT_EMAIL_VERIFICATION", default="optional")
ACCOUNT_EMAIL_SUBJECT_PREFIX = "[TCC] "
ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = True
ACCOUNT_PASSWORD_RESET_BY_CODE_ENABLED = False
LOGIN_URL = "/api/auth/contas/login/"
LOGIN_REDIRECT_URL = env("FRONTEND_URL", default="http://localhost:8080")
ACCOUNT_LOGOUT_REDIRECT_URL = LOGIN_URL

# --- E-mail (MailHog em dev) ---
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="mailhog")
EMAIL_PORT = env.int("EMAIL_PORT", default=1025)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="TCC <nao-responda@tcc.local>")

# --- JWT RS256 (emissão) ---
JWT_PRIVATE_KEY = env("JWT_PRIVATE_KEY", default="")
JWT_PRIVATE_KEY_PATH = env("JWT_PRIVATE_KEY_PATH", default="/run/secrets/jwt_private.pem")
JWT_ACCESS_MINUTOS = env.int("JWT_ACCESS_MINUTOS", default=15)
JWT_REFRESH_DIAS = env.int("JWT_REFRESH_DIAS", default=7)

# --- Auditoria: no auth-service grava direto, sem passar pela fila ---
AUDITORIA_HANDLER_LOCAL = "apps.auditoria.servicos.gravar_registro"

# --- Consumer: centraliza audit.registro e alertas de integridade ---
EVENT_HANDLERS = "apps.auditoria.eventos.HANDLERS"

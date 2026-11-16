"""Settings compartilhados pelos 6 serviços (django-environ).

Uso em ``config/settings/base.py`` de cada serviço::

    from tcc_common.settings_base import construir, env
    globals().update(construir(servico="monografias", apps=["apps.monografias"]))
"""

from pathlib import Path
from typing import Any

import environ

env = environ.Env()


def construir(servico: str, apps: list[str], base_dir: Path | None = None) -> dict[str, Any]:
    nome = f"{servico}-service"
    debug = env.bool("DEBUG", default=False)
    secret = env("DJANGO_SECRET_KEY", default="")
    if not secret:
        if not debug:
            raise RuntimeError("DJANGO_SECRET_KEY é obrigatório quando DEBUG=False.")
        secret = f"inseguro-apenas-dev-{servico}"
    redis_url = env("REDIS_URL", default="redis://localhost:6379/0")
    usa_fake = redis_url.startswith("fakeredis://")

    if usa_fake:
        caches = {
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": f"{servico}-default"},
            "sessoes": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": f"{servico}-sessoes"},
        }
    else:
        caches = {
            "default": {
                "BACKEND": "django_redis.cache.RedisCache",
                "LOCATION": redis_url,
                "KEY_PREFIX": f"django:{servico}",
                "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient", "IGNORE_EXCEPTIONS": True},
            },
            "sessoes": {
                "BACKEND": "django_redis.cache.RedisCache",
                "LOCATION": redis_url,
                "KEY_PREFIX": "sessao",
                "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
            },
        }

    return {
        "BASE_DIR": base_dir,
        "SERVICO_NOME": nome,
        "SERVICO_CURTO": servico,
        "SECRET_KEY": secret,
        "DEBUG": debug,
        "ALLOWED_HOSTS": env.list(
            "ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "[::1]", nome, "gateway", "testserver"]
        ),
        "INSTALLED_APPS": [
            "django.contrib.contenttypes",
            "django.contrib.auth",
            "django.contrib.staticfiles",
            "django.contrib.postgres",
            "corsheaders",
            "rest_framework",
            "django_filters",
            "drf_spectacular",
            "simple_history",
            "tcc_common.events",
            *apps,
        ],
        "MIDDLEWARE": [
            "django.middleware.security.SecurityMiddleware",
            "whitenoise.middleware.WhiteNoiseMiddleware",
            "corsheaders.middleware.CorsMiddleware",
            "tcc_common.middleware.request_id.RequestIdMiddleware",
            "tcc_common.middleware.rede_institucional.InstitutionalNetworkMiddleware",
            "django.middleware.common.CommonMiddleware",
            "django.middleware.clickjacking.XFrameOptionsMiddleware",
        ],
        "ROOT_URLCONF": "config.urls",
        "WSGI_APPLICATION": "config.wsgi.application",
        "TEMPLATES": [
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [base_dir / "templates"] if base_dir else [],
                "APP_DIRS": True,
                "OPTIONS": {
                    "context_processors": [
                        "django.template.context_processors.request",
                        "django.contrib.auth.context_processors.auth",
                    ]
                },
            }
        ],
        "DATABASES": {
            "default": {
                **env.db("DATABASE_URL", default=f"postgres://postgres:postgres@localhost:5432/{servico}_db"),
                "CONN_MAX_AGE": env.int("DB_CONN_MAX_AGE", default=60),
                "CONN_HEALTH_CHECKS": True,
            }
        },
        "CACHES": caches,
        "DEFAULT_AUTO_FIELD": "django.db.models.BigAutoField",
        "LANGUAGE_CODE": "pt-br",
        "TIME_ZONE": "America/Sao_Paulo",
        "USE_I18N": True,
        "USE_TZ": True,
        "STATIC_URL": f"/static/{servico}/",
        "STATIC_ROOT": env("STATIC_ROOT", default=str((base_dir or Path(".")) / "staticfiles")),
        "MEDIA_ROOT": env("MEDIA_ROOT", default=str((base_dir or Path(".")) / "media")),
        "MEDIA_URL": "/media/",
        "APPEND_SLASH": True,
        # DRF / OpenAPI
        "REST_FRAMEWORK": {
            "DEFAULT_AUTHENTICATION_CLASSES": ["tcc_common.auth.authentication.JWTAuthentication"],
            "DEFAULT_PERMISSION_CLASSES": ["tcc_common.auth.permissions.IsAutenticado"],
            "DEFAULT_PAGINATION_CLASS": "tcc_common.api.pagination.Paginacao",
            "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
            "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
            "EXCEPTION_HANDLER": "tcc_common.api.exceptions.exception_handler",
            "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
            "DEFAULT_THROTTLE_RATES": {
                "anon": env("THROTTLE_ANON", default="60/min"),
                "login": env("THROTTLE_LOGIN", default="20/min"),
            },
            "DATETIME_FORMAT": "iso-8601",
            "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
        },
        "SPECTACULAR_SETTINGS": {
            "TITLE": f"API {nome}",
            "DESCRIPTION": f"Sistema Distribuído de Monografias — {nome}",
            "VERSION": "1.0.0",
            "SERVE_INCLUDE_SCHEMA": False,
            "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
            "SERVE_AUTHENTICATION": [],
            "SWAGGER_UI_SETTINGS": {"persistAuthorization": True},
            "COMPONENT_SPLIT_REQUEST": True,
        },
        # Infra compartilhada
        "REDIS_URL": redis_url,
        "RABBITMQ_URL": env("RABBITMQ_URL", default="amqp://guest:guest@localhost:5672/%2F"),
        "READY_CHECK_RABBITMQ": env.bool("READY_CHECK_RABBITMQ", default=True),
        "CONSUMER_PREFETCH": env.int("CONSUMER_PREFETCH", default=10),
        "JWT_PUBLIC_KEY": env("JWT_PUBLIC_KEY", default=""),
        "JWT_PUBLIC_KEY_PATH": env("JWT_PUBLIC_KEY_PATH", default="/run/secrets/jwt_public.pem"),
        "JWKS_URL": env("JWKS_URL", default="http://auth-service:8001/.well-known/jwks.json"),
        "JWT_ISSUER": env("JWT_ISSUER", default="auth-service"),
        "SERVICE_TOKEN": env("SERVICE_TOKEN", default=""),
        "INSTITUTIONAL_CIDRS": env("INSTITUTIONAL_CIDRS", default="127.0.0.1/32,10.0.0.0/8,192.168.0.0/16"),
        "TRUSTED_PROXY_CIDRS": env("TRUSTED_PROXY_CIDRS", default="172.16.0.0/12"),
        "FRONTEND_URL": env("FRONTEND_URL", default="http://localhost:8080"),
        "SERVICOS_URLS": {
            "auth": env("AUTH_SERVICE_URL", default="http://auth-service:8001"),
            "monografias": env("MONOGRAFIAS_SERVICE_URL", default="http://monografias-service:8002"),
            "bancas": env("BANCAS_SERVICE_URL", default="http://bancas-service:8003"),
            "repositorio": env("REPOSITORIO_SERVICE_URL", default="http://repositorio-service:8004"),
        },
        # Segurança
        "CORS_ALLOWED_ORIGINS": env.list("CORS_ALLOWED_ORIGINS", default=[]),
        "SECURE_CONTENT_TYPE_NOSNIFF": True,
        "X_FRAME_OPTIONS": "DENY",
        "SECURE_REFERRER_POLICY": "same-origin",
        "SESSION_COOKIE_HTTPONLY": True,
        "CSRF_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SECURE": env.bool("COOKIES_SEGUROS", default=not debug),
        "CSRF_COOKIE_SECURE": env.bool("COOKIES_SEGUROS", default=not debug),
        "CSRF_TRUSTED_ORIGINS": env.list("CSRF_TRUSTED_ORIGINS", default=["http://localhost:8080"]),
        "USE_X_FORWARDED_HOST": True,
        "DATA_UPLOAD_MAX_MEMORY_SIZE": 5 * 1024 * 1024,
        "FILE_UPLOAD_MAX_MEMORY_SIZE": 2_621_440,
        # Logs JSON
        "LOGGING": {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": "tcc_common.api.logging.JsonFormatter", "servico": nome}},
            "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
            "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
            "loggers": {
                "django.db.backends": {"level": "WARNING"},
                "pika": {"level": "WARNING"},
            },
        },
    }

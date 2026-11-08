"""Settings do repositorio-service."""

from pathlib import Path

from tcc_common.settings_base import construir, env

BASE_DIR = Path(__file__).resolve().parents[2]
globals().update(construir(servico="repositorio", porta=8004, base_dir=BASE_DIR, apps=["apps.indexacao"]))

MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.common.CommonMiddleware"),  # noqa: F405
    "django.middleware.http.ConditionalGetMiddleware",
)

FTS_CONFIG = env("FTS_CONFIG", default="portuguese")
FTS_MAX_CHARS = env.int("FTS_MAX_CHARS", default=300_000)  # tsvector tem limite de 1 MB
EXTRACAO_MAX_PAGINAS = env.int("EXTRACAO_MAX_PAGINAS", default=800)
EXTRACAO_TIMEOUT_S = env.int("EXTRACAO_TIMEOUT_S", default=180)
BUSCA_CACHE_TTL_S = env.int("BUSCA_CACHE_TTL_S", default=300)
BUSCA_CACHE_ATIVO = env.bool("BUSCA_CACHE_ATIVO", default=True)
HTTP_CACHE_MAX_AGE = env.int("HTTP_CACHE_MAX_AGE", default=60)

REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = ["rest_framework.throttling.AnonRateThrottle"]  # noqa: F405

EVENT_HANDLERS = "apps.indexacao.eventos.HANDLERS"

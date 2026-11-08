"""Settings do monografias-service."""

from pathlib import Path

from tcc_common.settings_base import construir, env

BASE_DIR = Path(__file__).resolve().parents[2]
globals().update(construir(servico="monografias", porta=8002, base_dir=BASE_DIR, apps=["apps.monografias"]))

# --- Upload (Fase 2, item 4) ---
MAX_UPLOAD_MB = env.int("MAX_UPLOAD_MB", default=50)
SUBMISSOES_POR_HORA = env.int("SUBMISSOES_POR_HORA", default=5)
UPLOAD_LOCK_TTL_S = env.int("UPLOAD_LOCK_TTL_S", default=600)
MIN_PALAVRAS_CHAVE = env.int("MIN_PALAVRAS_CHAVE", default=3)
FILE_UPLOAD_HANDLERS = ["django.core.files.uploadhandler.TemporaryFileUploadHandler"]

EVENT_HANDLERS = "apps.monografias.eventos.HANDLERS"

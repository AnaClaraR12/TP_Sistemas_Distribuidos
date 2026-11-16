from pathlib import Path

from tcc_common.settings_base import construir, env

BASE_DIR = Path(__file__).resolve().parents[2]
globals().update(construir(servico="relatorios", base_dir=BASE_DIR, apps=["apps.relatorios"]))

RELATORIO_CACHE_TTL_S = env.int("RELATORIO_CACHE_TTL_S", default=60)

EVENT_HANDLERS = "apps.relatorios.eventos.HANDLERS"

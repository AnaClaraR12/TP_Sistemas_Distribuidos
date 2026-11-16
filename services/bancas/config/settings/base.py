from pathlib import Path

from tcc_common.settings_base import construir, env

BASE_DIR = Path(__file__).resolve().parents[2]
globals().update(construir(servico="bancas", base_dir=BASE_DIR, apps=["apps.bancas"]))

BANCA_MIN_MEMBROS = env.int("BANCA_MIN_MEMBROS", default=3)
BANCA_DURACAO_PADRAO_MIN = env.int("BANCA_DURACAO_PADRAO_MIN", default=120)
NOTA_MINIMA = env.float("NOTA_MINIMA", default=6.0)
TOKEN_EXTERNO_DIAS_APOS_BANCA = env.int("TOKEN_EXTERNO_DIAS_APOS_BANCA", default=7)
EXTERNO_RATE_LIMIT_POR_MIN = env.int("EXTERNO_RATE_LIMIT_POR_MIN", default=30)
URL_ASSINADA_TTL_S = env.int("URL_ASSINADA_TTL_S", default=300)

EVENT_HANDLERS = "apps.bancas.eventos.HANDLERS"

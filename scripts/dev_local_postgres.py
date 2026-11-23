"""Sobe um PostgreSQL 16 embutido (pacote ``pgserver``) para rodar os testes SEM Docker.

Uso (Linux)::

    pip install pgserver tzdata
    python3 scripts/dev_local_postgres.py           # imprime a DATABASE_URL base

O alvo oficial do projeto é Docker Compose (Postgres do container); este script existe
apenas para desenvolvimento/testes locais em máquinas sem Docker.
Observação: o build embutido não traz as extensões contrib (unaccent, pg_trgm) — as
migrações tratam isso (extensões são opcionais e a busca normaliza acentos em Python).
"""

import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def _garantir_timezones() -> None:
    """Garante share/postgresql/timezone no pgserver (alguns builds não trazem): copia do pacote tzdata."""
    import shutil

    import pgserver
    import tzdata

    destino = Path(pgserver.__file__).parent / "pginstall" / "share" / "postgresql" / "timezone"
    if not destino.exists():
        shutil.copytree(Path(tzdata.__file__).parent / "zoneinfo", destino)


def url_do_banco(uri: str, banco: str) -> str:
    """Troca o database da URI mantendo host, porta e query.

    No Linux o pgserver conecta por socket Unix (``postgresql://postgres:@/postgres?host=/caminho``):
    a query também tem barras, então não dá para trocar o nome com ``rsplit("/")``.
    """
    partes = urlsplit(uri)
    return urlunsplit(partes._replace(path=f"/{banco}"))


def criar_databases(uri: str) -> None:
    import psycopg

    with psycopg.connect(uri, autocommit=True) as c:
        existentes = {r[0] for r in c.execute("select datname from pg_database")}
        for d in ("auth_db", "monografias_db", "bancas_db", "repositorio_db", "notificacoes_db", "relatorios_db"):
            if d not in existentes:
                c.execute(f'CREATE DATABASE "{d}"')


def obter_uri() -> str:
    import pgserver

    _garantir_timezones()
    pasta = Path(os.environ.get("PG_LOCAL_DIR", Path(tempfile.gettempdir()) / "tcc_pg_local"))
    pasta.mkdir(parents=True, exist_ok=True)
    srv = pgserver.get_server(str(pasta), cleanup_mode=None)
    return srv.get_uri()


if __name__ == "__main__":
    uri = obter_uri()
    criar_databases(uri)
    print(url_do_banco(uri, "postgres"))
    sys.exit(0)

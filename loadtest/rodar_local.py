"""Executa o teste de carga LOCALMENTE (sem Docker) em 3 cenários e grava os números reais.

Cenários: (A) 1 réplica sem cache, (B) 1 réplica com cache Redis, (C) 3 réplicas com cache.
Infra local: PostgreSQL 16 embutido (pgserver), servidor Redis-compatível em TCP (fakeredis) e
réplicas do repositorio-service servidas por waitress; o Locust balanceia entre as réplicas.

Uso: python loadtest/rodar_local.py --usuarios 400 --duracao 60
Saída: loadtest/resultados/<cenario>_stats.csv, cache_<cenario>.json e resumo_local.json
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import requests

RAIZ = Path(__file__).resolve().parents[1]
SERVICO = RAIZ / "services" / "repositorio"
RESULTADOS = RAIZ / "loadtest" / "resultados"
PY = sys.executable
PORTA_REDIS = 6390


def iniciar_redis() -> subprocess.Popen:
    codigo = (
        f"import fakeredis; s = fakeredis.TcpFakeServer(('127.0.0.1', {PORTA_REDIS}), server_type='redis'); "
        "s.daemon_threads = True; s.serve_forever()"
    )
    p = subprocess.Popen([PY, "-c", codigo])
    time.sleep(1.5)
    return p


def ambiente(db_url: str, cache: bool, media: Path) -> dict:
    env = dict(os.environ)
    env.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings.prod",
            "DJANGO_SECRET_KEY": "carga-local-nao-usar",
            "DATABASE_URL": db_url,
            "REDIS_URL": f"redis://127.0.0.1:{PORTA_REDIS}/0",
            "MEDIA_ROOT": str(media),
            "ALLOWED_HOSTS": "127.0.0.1,localhost",
            "THROTTLE_ANON": "100000000/min",
            "LOG_LEVEL": "ERROR",
            "BUSCA_CACHE_ATIVO": "1" if cache else "0",
            "READY_CHECK_RABBITMQ": "0",
            "DB_CONN_MAX_AGE": "300",
        }
    )
    return env


def amostrar(procs: list[psutil.Process], parar: threading.Event, saida: dict) -> None:
    cpus, mems = [], []
    for p in procs:
        p.cpu_percent(None)
    while not parar.wait(1.0):
        try:
            cpus.append(sum(p.cpu_percent(None) for p in procs))
            mems.append(sum(p.memory_info().rss for p in procs) / 1024 / 1024)
        except psutil.Error:
            break
    saida["cpu_media_pct"] = round(sum(cpus) / max(len(cpus), 1), 1)
    saida["cpu_pico_pct"] = round(max(cpus or [0]), 1)
    saida["mem_pico_mb"] = round(max(mems or [0]), 1)


def cenario(
    nome: str, replicas: int, cache: bool, db_url: str, media: Path, usuarios: int, duracao: int, taxa: int
) -> dict:
    print(f"\n=== Cenário {nome}: {replicas} réplica(s), cache={'sim' if cache else 'não'} ===")
    requests.Session()  # aquece import
    import redis

    redis.Redis(port=PORTA_REDIS).flushall()
    env = ambiente(db_url, cache, media)
    servidores = []
    for i in range(replicas):
        porta = 9001 + i
        servidores.append(
            subprocess.Popen(
                [
                    PY,
                    "-m",
                    "waitress",
                    f"--listen=127.0.0.1:{porta}",
                    "--threads=16",
                    "--connection-limit=4000",
                    "--backlog=4096",
                    "--channel-timeout=60",
                    "config.wsgi:application",
                ],
                cwd=SERVICO,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
    backends = [f"http://127.0.0.1:{9001 + i}" for i in range(replicas)]
    for b in backends:
        for _ in range(60):
            try:
                if requests.get(b + "/health/", timeout=2).status_code == 200:
                    break
            except requests.RequestException:
                time.sleep(0.5)
    medidas: dict = {}
    parar = threading.Event()
    procs = []
    for s in servidores:  # no Windows o python.exe do venv é um lançador: mede também os filhos
        p = psutil.Process(s.pid)
        procs += [p, *p.children(recursive=True)]
    t = threading.Thread(target=amostrar, args=(procs, parar, medidas))
    t.start()
    prefixo = RESULTADOS / nome
    cache_json = RESULTADOS / f"cache_{nome}.json"
    env_locust = {**os.environ, "BACKENDS": ",".join(backends), "CACHE_STATS_FILE": str(cache_json)}
    subprocess.run(
        [
            PY,
            "-m",
            "locust",
            "-f",
            str(RAIZ / "loadtest" / "locustfile.py"),
            "--headless",
            "-u",
            str(usuarios),
            "-r",
            str(taxa),
            "-t",
            f"{duracao}s",
            "--host",
            backends[0],
            "--csv",
            str(prefixo),
            "--only-summary",
            "--loglevel",
            "WARNING",
        ],
        env=env_locust,
        check=False,
    )
    parar.set()
    t.join()
    for s in servidores:
        s.terminate()
    for s in servidores:
        s.wait(timeout=20)
    agregado = {}
    with open(f"{prefixo}_stats.csv", encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            if linha["Name"] == "Aggregated":
                agregado = linha
    busca = {}
    with open(f"{prefixo}_stats.csv", encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            if linha["Name"].startswith("busca"):
                busca = linha
    contagem = json.loads(cache_json.read_text()) if cache_json.exists() else {}
    total_busca = sum(v for k, v in contagem.items() if not k.startswith("nginx_")) or 1
    resultado = {
        "cenario": nome,
        "replicas": replicas,
        "cache": cache,
        "usuarios": usuarios,
        "duracao_s": duracao,
        "requisicoes": int(agregado.get("Request Count", 0)),
        "falhas": int(agregado.get("Failure Count", 0)),
        "rps": round(float(agregado.get("Requests/s", 0)), 1),
        "p50_ms": float(agregado.get("50%", 0)),
        "p95_ms": float(agregado.get("95%", 0)),
        "p99_ms": float(agregado.get("99%", 0)),
        "busca_p50_ms": float(busca.get("50%", 0)),
        "busca_p95_ms": float(busca.get("95%", 0)),
        "taxa_erro_pct": round(
            100 * int(agregado.get("Failure Count", 0)) / max(int(agregado.get("Request Count", 1)), 1), 2
        ),
        "cache_hit_pct": round(100 * contagem.get("HIT", 0) / total_busca, 1) if cache else 0.0,
        **medidas,
    }
    print(json.dumps(resultado, ensure_ascii=False))
    return resultado


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--usuarios", type=int, default=400)
    ap.add_argument("--duracao", type=int, default=60)
    ap.add_argument("--taxa", type=int, default=100)
    ap.add_argument("--documentos", type=int, default=3000)
    ap.add_argument("--cenarios", default="A,B,C", help="subconjunto, ex.: B,C")
    a = ap.parse_args()
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(RAIZ / "scripts"))
    import psycopg
    from dev_local_postgres import obter_uri

    base = obter_uri().rsplit("/", 1)[0]
    with psycopg.connect(base + "/postgres", autocommit=True) as c:
        if not c.execute("select 1 from pg_database where datname='repositorio_carga'").fetchone():
            c.execute("CREATE DATABASE repositorio_carga")
    db_url = base + "/repositorio_carga"
    media = RESULTADOS / "_media"
    redis_proc = iniciar_redis()
    try:
        env = ambiente(db_url, True, media)
        subprocess.run([PY, "manage.py", "migrate", "--noinput", "-v", "0"], cwd=SERVICO, env=env, check=True)
        subprocess.run(
            [PY, str(RAIZ / "loadtest" / "popular_base.py"), str(a.documentos)], cwd=SERVICO, env=env, check=True
        )
        definicoes = {
            "A": ("A_sem_cache_1_replica", 1, False),
            "B": ("B_com_cache_1_replica", 1, True),
            "C": ("C_com_cache_3_replicas", 3, True),
        }
        resultados = [
            cenario(nome, rep, cache, db_url, media, a.usuarios, a.duracao, a.taxa)
            for chave, (nome, rep, cache) in definicoes.items()
            if chave in a.cenarios.split(",")
        ]
        (RESULTADOS / "resumo_local.json").write_text(
            json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print("\nResumo gravado em", RESULTADOS / "resumo_local.json")
    finally:
        redis_proc.terminate()


if __name__ == "__main__":
    main()

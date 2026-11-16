"""Teste de carga — "pico de defesa" no repositório público.

Mistura: 80 % buscas (consultas variadas com repetição realista — distribuição Zipf),
15 % detalhe/download, 5 % listagens (cursos, orientadores, página inicial).

Contra o gateway (Docker):
    locust -f loadtest/locustfile.py --host http://localhost:8080 --headless -u 1000 -r 50 -t 5m --csv loadtest/resultados/pico

Balanceamento no cliente (réplicas locais sem Nginx): BACKENDS=http://127.0.0.1:9001,http://127.0.0.1:9002
"""

import json
import os
import random
from collections import Counter

from locust import FastHttpUser, between, events, task

TERMOS = [
    "sistemas distribuidos",
    "redis",
    "cache",
    "microsservicos",
    "rabbitmq",
    "filas",
    "postgresql",
    "busca textual",
    "seguranca",
    "jwt",
    "docker",
    "kubernetes",
    "nuvem",
    "elasticidade",
    "iot",
    "agricultura",
    "blockchain",
    "aprendizado de maquina",
    "classificacao",
    "redes neurais",
    "acessibilidade",
    "escalabilidade",
    "desempenho",
    "banco de dados",
    "indices",
    "api rest",
    "devops",
    "integridade",
    "replicacao",
    "consistencia",
    "tolerancia a falhas",
    "algoritmos",
    "grafos",
    "compiladores",
    "engenharia de software",
    "testes",
    "qualidade",
    "usabilidade",
    "visao computacional",
    "processamento de linguagem natural",
    "criptografia",
    "sensores",
    "mobile",
    "web",
]
PESOS = [1 / (i + 1) for i in range(len(TERMOS))]  # Zipf: poucos termos muito populares
BACKENDS = [b.strip().rstrip("/") for b in os.environ.get("BACKENDS", "").split(",") if b.strip()]
IDS: list[str] = []
CONTAGEM_CACHE: Counter = Counter()


@events.test_start.add_listener
def _carregar_ids(environment, **kw):
    """Coleta IDs publicados para os cenários de detalhe/download."""
    import requests

    base = BACKENDS[0] if BACKENDS else environment.host
    try:
        r = requests.get(f"{base}/api/repositorio/monografias/?limit=50&ordenar=recentes", timeout=10)
        IDS.extend(m["id"] for m in r.json().get("results", []))
    except (requests.RequestException, ValueError, KeyError) as exc:
        print("aviso: não foi possível carregar IDs:", exc)


@events.request.add_listener
def _contar_cache(name, response, exception, **kw):
    if exception or response is None or not name.startswith("busca"):
        return
    cabecalhos = response.headers or {}
    CONTAGEM_CACHE[cabecalhos.get("X-Cache", "-")] += 1
    if cabecalhos.get("X-Proxy-Cache"):
        CONTAGEM_CACHE["nginx_" + cabecalhos["X-Proxy-Cache"]] += 1


@events.quitting.add_listener
def _salvar_cache(environment, **kw):
    destino = os.environ.get("CACHE_STATS_FILE")
    if destino:
        with open(destino, "w", encoding="utf-8") as f:
            json.dump(dict(CONTAGEM_CACHE), f)


class Visitante(FastHttpUser):
    wait_time = between(0.5, 2.0)

    def _url(self, caminho: str) -> str:
        return (random.choice(BACKENDS) + caminho) if BACKENDS else caminho

    @task(80)
    def buscar(self):
        termo = random.choices(TERMOS, weights=PESOS)[0]
        params = f"?busca={termo.replace(' ', '+')}"
        sorteio = random.random()
        if sorteio < 0.15:
            params += f"&ano_defesa={random.randint(2018, 2026)}"
        elif sorteio < 0.25:
            params += "&ordenar=recentes"
        if random.random() < 0.1:
            params += f"&offset={random.choice([10, 20])}"
        self.client.get(
            self._url("/api/repositorio/monografias/" + params), name="busca /api/repositorio/monografias/?busca="
        )

    @task(10)
    def detalhe(self):
        if IDS:
            self.client.get(
                self._url(f"/api/repositorio/monografias/{random.choice(IDS)}/"), name="detalhe /monografias/{id}/"
            )

    @task(5)
    def download(self):
        if IDS:
            self.client.get(
                self._url(f"/api/repositorio/monografias/{random.choice(IDS[:10])}/download/"),
                name="download /{id}/download/",
            )

    @task(5)
    def listagens(self):
        caminho = random.choice(
            ["/api/repositorio/cursos/", "/api/repositorio/orientadores/", "/api/repositorio/monografias/"]
        )
        self.client.get(self._url(caminho), name="listagem " + caminho)

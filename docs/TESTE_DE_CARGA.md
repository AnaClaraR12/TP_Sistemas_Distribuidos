# Teste de carga — pico de defesa no repositório público

## Como foi medido (execução real em Linux, 22/11/2026)

* **Máquina:** Intel Core i5-13450HX (16 threads), **Ubuntu 24.04 LTS no WSL2** (kernel 6.18, 11 GB de RAM para o
  Linux) e Docker Engine 29.9.3. Gerador de carga e sistema na **mesma máquina** (o Locust disputa CPU com o sistema).
* **Base:** **3 000 monografias publicadas** sintéticas (título, resumo, palavras-chave e ~3 000 palavras de corpo,
  `tsvector` + GIN), geradas por `loadtest/popular_base.py`.
* **Carga:** Locust (`loadtest/locustfile.py`): **80 % buscas** (termos com distribuição Zipf, 15 % com filtro de ano,
  10 % ordenação por recentes, 10 % paginação), **15 % detalhe/download**, **5 % listagens**; espera de 0,5–2 s entre
  ações (≈ 0,8 req/s por usuário).
* **Dois ambientes:**
  1. **Docker (alvo oficial):** os 23 containers do `docker-compose.yml`, tráfego pelo **gateway Nginx**
     (`proxy_cache`), Redis real, Gunicorn com `GUNICORN_WORKERS=2` × 4 threads por réplica. Limites de taxa
     liberados para o teste, como em `loadtest/README.md` (um único IP gera toda a carga).
  2. **Executor local sem Docker:** `python3 loadtest/rodar_local.py` — mesmo código do `repositorio-service`
     servido por **Gunicorn** (2 workers × 4 threads por réplica), PostgreSQL 16 embutido e servidor
     Redis-compatível em TCP (fakeredis); sem Nginx, o Locust balanceia entre as réplicas.
* **Cenários:** (A) 1 réplica sem cache · (B) 1 réplica com cache · (C) 3 réplicas com cache.

## Resultados no Docker — pelo gateway, 3 min por cenário

| Cenário | Usuários | Requisições | RPS | p50 | p95 | p99 | Erros | HIT do Nginx (buscas) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| B — cache, 1 réplica | 1 000 | 114 155 | 680,8 | 2 ms | 700 ms | 5 300 ms | **0 %** | 95,0 % |
| C — cache, 3 réplicas | 1 000 | 135 911 | **799,6** | **2 ms** | **44 ms** | 250 ms | **0 %** | 96,3 % |
| C — cache, 3 réplicas | 2 000 | 213 245 | **1 259,4** | 15 ms | 1 000 ms | 4 300 ms | **0 %** | 97,3 % |

Fonte: `loadtest/resultados/execucao_linux_docker_1000u/` e `execucao_linux_docker_2000u/` (`*_stats.csv`,
`cache_*.json`, `docker_stats_*.txt`). Rampa de 50 usuários/s (1 000) e 100 usuários/s (2 000).

**Leitura:**
* Com **3 réplicas e 1 000 usuários** a vazão (~800 req/s) é toda a demanda gerada (1 000 × 0,8 req/s): o sistema
  não enfileira, **p95 de 44 ms** e nenhum erro. O `proxy_cache` do Nginx responde ~96 % das buscas; o que passa
  chega ao Redis. As 3 réplicas ficaram em ~10 % de CPU cada (`docker stats` no meio do teste).
* Com **1 réplica**, os *misses* do início (cache frio) enfileiram nos 8 threads de uma réplica só: mediana de 2 ms,
  mas cauda longa (p95 700 ms). É o efeito que as réplicas resolvem.
* Com **2 000 usuários** o sistema seguiu **sem erros** a 1 259 req/s, mas o próprio Locust avisou *"CPU usage above
  90%"*: com um processo só, na mesma máquina, o **gerador de carga virou o gargalo** (as réplicas ficaram em ~17 % de
  CPU e o gateway em ~115 %, ou seja, pouco mais de 1 núcleo). A cauda (p95 1 s) mede em boa parte o atraso do próprio
  Locust; para medir 2 000 usuários com precisão, rode o Locust distribuído (`--processes`) ou em outra máquina.

## Resultados sem Docker (executor local) — 400 e 1 000 usuários

| Cenário | Usuários / duração | Requisições | RPS | p50 | p95 | p99 | Erros | HIT do Redis (buscas) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| A — sem cache, 1 réplica | 400 / 60 s | 8 926 | 161,6 | 1 300 ms | 1 700 ms | 1 900 ms | **0 %** | — |
| B — cache, 1 réplica | 400 / 60 s | 18 237 | 329,5 | 8 ms | 47 ms | 210 ms | **0 %** | 95,1 % |
| C — cache, 3 réplicas | 400 / 60 s | 18 415 | 332,7 | **7 ms** | **39 ms** | 160 ms | **0 %** | 95,0 % |
| A — sem cache, 1 réplica | 1 000 / 120 s | 17 678 | 155,8 | 4 800 ms | 6 400 ms | 6 600 ms | **0 %** | — |
| B — cache, 1 réplica | 1 000 / 120 s | 53 763 | 473,7 | 700 ms | 1 500 ms | 1 600 ms | **0 %** | 97,8 % |
| C — cache, 3 réplicas | 1 000 / 120 s | 76 839 | 690,9 | 68 ms | 700 ms | 900 ms | **0 %** | 98,3 % |

Fonte: `loadtest/resultados/execucao_linux_400u/` e `execucao_linux_1000u/` (`*_stats.csv`, `resumo_local.json`).

**Leitura:** sem cache, a réplica única satura (cada busca FTS custa ~10–20 ms de CPU Python+Postgres): a vazão
para em ~160 req/s e as requisições enfileiram. Com o cache ~95 % das buscas não tocam o banco: **a 400 usuários o p95
cai de 1 700 ms para 47 ms (36×) e a vazão dobra**; com 3 réplicas, 39 ms. A 400 usuários, B e C estão limitados pela
demanda (~330 req/s), não pelo sistema. A 1 000 usuários o executor local fica abaixo do Docker porque o servidor
Redis falso (fakeredis, Python de uma thread) e a falta do `proxy_cache` do Nginx limitam a vazão; mesmo assim,
**nenhuma conexão falhou**.

## Comparação com a meta sugerida

| Meta | Medido (Linux) |
|---|---|
| erro < 1 % | ✅ **0 %** em todos os cenários, inclusive 2 000 usuários no Docker |
| p95 < 500 ms com cache | ✅ **44 ms** com 1 000 usuários (Docker, 3 réplicas); 39–47 ms a 400 usuários (local) |
| 1 000–2 000 usuários | ✅ 1 000 usuários dentro da meta (Docker, 3 réplicas); 🟡 2 000 usuários sem erros, mas p95 de 1 s com o gerador de carga saturado na mesma máquina |

## Camadas de cache e por que funcionam

1. **Nginx `proxy_cache`** (30 s, `proxy_cache_lock` coalesce requisições idênticas) — no Docker respondeu 95–97 % das
   buscas no teste acima (`X-Proxy-Cache: HIT`); não existe no executor local.
2. **Redis `busca:<versao>:<sha256(query normalizada)>`** (300 s) com lock anti-*stampede* (`busca_lock:<hash>`) —
   responsável pela queda de latência medida; `busca:versao` é incrementado a cada publicação (invalidação total, O(1)).
3. **HTTP `Cache-Control: public, max-age=60` + ETag** (304 em revalidação) — reduz tráfego de clientes reais.

## Resiliência (isolamento de falhas)

Por construção, a busca pública depende apenas de `repositorio-service` + Postgres + Redis (com degradação para
consulta direta se o Redis cair): **não** depende de RabbitMQ, `notificacoes-service`, `monografias-service` nem dos
workers. Demonstração no Docker (roteiro em `docs/ROTEIRO_DEMO.md`):

```bash
docker compose stop notificacoes-worker repositorio-worker   # durante a carga
# a busca continua respondendo; novas submissões acumulam em repositorio.monografia.submetida (painel :15672)
docker compose start notificacoes-worker repositorio-worker   # as filas esvaziam e os e-mails chegam
```

Coberto em teste: consumer com broker fora não perde eventos (outbox mantém pendentes —
`test_publish_outbox_falha_mantem_pendente`); Redis fora não derruba a busca (`obter_ou_calcular` calcula direto).

## Banco: uso do índice GIN

```sql
EXPLAIN ANALYZE SELECT monografia_id FROM indexacao_documentoindexado
 WHERE publico AND search_vector @@ websearch_to_tsquery('portuguese', 'sistemas distribuidos');
-- esperado: Bitmap Index Scan on doc_search_vector_gin
```

O índice `doc_search_vector_gin` existe (teste `test_busca_usa_indice_gin_explain`); páginas limitadas a 50 itens;
`defer("texto_completo", "search_vector")` evita trafegar o corpo do PDF nas listagens.

## Histórico: primeira medição, no Windows (substituída pela medição em Linux acima)

A primeira medição foi feita durante o desenvolvimento numa estação **Windows 11 sem Docker** (i5-13600KF, 32 GB),
com o `repositorio-service` servido por *waitress* (o Gunicorn não roda no Windows). A 400 usuários: A 138 req/s e p95
1 900 ms; B 307 req/s e p95 94 ms; C 313 req/s e p95 25 ms, todos com 0 % de erros. Acima de ~700 conexões
simultâneas o Windows passou a recusar conexões no loopback (`WinError 10061`), o que impediu medir 1 000 usuários
lá. No Linux esse limite não existe: as execuções com 1 000 e 2 000 usuários acima terminaram com 0 falhas.
CSVs: `loadtest/resultados/execucao_400u/` e `execucao_1000u_*`.

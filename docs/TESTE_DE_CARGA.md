# Teste de carga — pico de defesa no repositório público

## Como foi medido (execução real desta entrega)

* **Máquina:** Intel Core i5-13600KF (20 threads), 32 GB RAM, Windows 11 — **sem Docker** (ver DECISOES.md).
* **Sistema sob teste:** `repositorio-service` real (mesmo código do container) servido por *waitress*
  (16 threads/processo), PostgreSQL 16 embutido, servidor Redis-compatível em TCP (fakeredis),
  **3 000 monografias publicadas** sintéticas (título, resumo, palavras-chave e ~3 000 palavras de corpo, `tsvector` + GIN).
* **Carga:** Locust (`loadtest/locustfile.py`): **80 % buscas** (termos com distribuição Zipf, 15 % com filtro de ano,
  10 % ordenação por recentes, 10 % paginação), **15 % detalhe/download**, **5 % listagens**; espera de 0,5–2 s entre ações.
* **Cenários:** (A) 1 réplica sem cache · (B) 1 réplica com cache Redis · (C) 3 réplicas com cache (Locust balanceando entre réplicas).
* **Reprodução:** `python loadtest/rodar_local.py --usuarios 400 --duracao 60` (CSVs brutos em `loadtest/resultados/`).

## Resultados — 400 usuários simultâneos, 60 s (rampa 100 usuários/s)

| Cenário | Requisições | RPS | p50 | p95 | p99 | Erros | HIT do cache (buscas) |
|---|---:|---:|---:|---:|---:|---:|---:|
| A — sem cache, 1 réplica | 8 175 | 138,0 | 1 600 ms | 1 900 ms | 2 000 ms | **0 %** | — |
| B — cache Redis, 1 réplica | 18 162 | 306,9 | 21 ms | 94 ms | 290 ms | **0 %** | 94,9 % |
| C — cache Redis, 3 réplicas | 18 514 | 312,7 | **7 ms** | **25 ms** | 130 ms | **0 %** | 95,0 % |

Fonte: `loadtest/resultados/execucao_400u/` (`*_stats.csv`, `resumo_local.json`).

**Leitura:** sem cache a réplica única satura (cada busca FTS custa ~10–20 ms de CPU Python+Postgres e o GIL limita a
1 núcleo): a vazão para em ~138 req/s e as requisições enfileiram (p95 1,9 s). Com o cache Redis ~95 % das buscas
são servidas sem tocar no banco: **p95 cai 20× (1 900 → 94 ms) e a vazão dobra**. Com 3 réplicas o p95 cai para
**25 ms**. Em B e C a vazão (~310 req/s) é limitada pela demanda gerada (400 usuários com espera média de 1,25 s ≈
320 req/s), não pelo sistema — a métrica que diferencia os cenários é a latência.

## Resultados — rampa até 1 000 usuários

| Execução | Observação | Números |
|---|---|---|
| A (sem cache), 1 000 usuários, rampa 100/s | completa, servidor saturado | 7 973 req, **132 req/s**, p50 6,2 s, **p95 6,6 s**, 0 % erros; CPU média 88 % (≈1 núcleo, GIL), memória 159 MB |
| C (cache, 3 réplicas), rampa 20/s até 1 000 | estável até ~620 usuários | até 620 usuários: **371 req/s, p95 51 ms, 0 erros** (CPU somada das 3 réplicas: 76 % em média no teste inteiro) |
| B e C acima de ~700 conexões simultâneas | **limite do ambiente local** | o Windows passou a recusar conexões no loopback (`WinError 10061`, ~2 s de espera = retransmissão de SYN): a partir desse ponto 100 % das novas conexões falham, nas 3 réplicas ao mesmo tempo |

Fonte: `loadtest/resultados/execucao_1000u_*`. A falha "em degrau", simultânea em processos independentes e
inexistente no cenário lento A (em que as conexões ficam abertas esperando), indica limite da pilha TCP/loopback
do Windows com gerador de carga e servidores na mesma máquina (e do laço de *accept* single-thread do waitress),
e não do sistema. **Meta de 1 000–2 000 usuários deve ser medida no Docker/Linux** (Gunicorn multiprocesso +
Nginx com `proxy_cache`), com o gerador de carga em outra máquina — roteiro em `loadtest/README.md`.

## Comparação com a meta sugerida

| Meta (Fase 11) | Medido |
|---|---|
| erro < 1 % | ✅ 0 % em todos os cenários a 400 usuários e em C até ~620 usuários |
| p95 < 500 ms com cache | ✅ 94 ms (1 réplica) e 25 ms (3 réplicas) a 400 usuários; 51 ms a ~620 usuários |
| 1 000–2 000 usuários | 🟡 não atingido no ambiente local (limite do loopback do Windows acima de ~700 conexões); executar no Docker |

## Camadas de cache e por que funcionam

1. **Nginx `proxy_cache`** (30 s, `proxy_cache_lock` coalesce requisições idênticas) — não usado no teste local; no
   Docker reduz ainda mais a carga nas réplicas (`X-Proxy-Cache: HIT`).
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

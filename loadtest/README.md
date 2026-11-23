# Teste de carga — pico de defesa

`locustfile.py`: 80 % buscas (termos com distribuição Zipf, filtros ocasionais, paginação), 15 % detalhe/download,
5 % listagens. Registra a proporção de `X-Cache: HIT/MISS` (e `X-Proxy-Cache` do Nginx).

## No Docker (alvo oficial)

```bash
# 1) libere os limites para o teste (um único IP gera toda a carga)
echo "THROTTLE_ANON=100000000/min" >> .env
echo "GATEWAY_RATE_REPOSITORIO=100000r/s" >> .env
docker compose up -d
# 2) base volumosa (opcional): 3000 documentos sintéticos
docker compose cp loadtest/popular_base.py repositorio-service:/app/popular_base.py
docker compose exec repositorio-service python popular_base.py 3000
# 3) cenários
BUSCA_CACHE_ATIVO=0 docker compose up -d repositorio-service   # sem cache
make loadtest                                                   # 1000 usuários, rampa 50/s, 5 min
docker compose up -d repositorio-service                        # com cache
make loadtest
make scale && make loadtest                                     # 3 réplicas
docker stats --no-stream                                        # CPU/memória
```

## Sem Docker (Linux)

```bash
pip install -e libs/tcc_common -r services/repositorio/requirements-dev.txt pgserver tzdata locust psutil
python3 loadtest/rodar_local.py --usuarios 400 --duracao 60
```

Sobe Postgres embutido, Redis-compatível em TCP e N réplicas (Gunicorn, `GUNICORN_WORKERS` workers cada, padrão 2) do repositorio-service; o Locust balanceia
entre as réplicas (`BACKENDS`). CSVs e `resumo_local.json` ficam em `loadtest/resultados/`.

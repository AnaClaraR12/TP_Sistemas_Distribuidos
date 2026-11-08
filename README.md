# Sistema Distribuído de Monografias (TCC)

Trabalho de **Sistemas Distribuídos** (Prof. Alessandro Vivas Andrade): cadastro, submissão, avaliação
e publicação de monografias com **6 microsserviços Django**, **RabbitMQ**, **Redis**, **PostgreSQL**
(database por serviço), **API Gateway Nginx** e **frontend React**.

* Arquitetura e fluxos: [docs/ARQUITETURA.md](docs/ARQUITETURA.md) · Decisões: [docs/DECISOES.md](docs/DECISOES.md)
* Eventos: [docs/EVENTOS.md](docs/EVENTOS.md) · API: [docs/API.md](docs/API.md) · Segurança: [docs/SEGURANCA.md](docs/SEGURANCA.md)
* Carga: [docs/TESTE_DE_CARGA.md](docs/TESTE_DE_CARGA.md) · Demonstração: [docs/ROTEIRO_DEMO.md](docs/ROTEIRO_DEMO.md)
* Rastreabilidade com o enunciado: [docs/CHECKLIST.md](docs/CHECKLIST.md) · Verificação com o sistema real: [docs/VERIFICACAO.md](docs/VERIFICACAO.md)

## Pré-requisitos (Linux ou WSL2)

* Docker 24+ com Docker Compose v2, `make`, `openssl`
* Python 3.12+ (só para `make seed`, `make e2e` e `make loadtest` no host: `pip install requests locust pytest`)

## Subir o sistema

```bash
cp .env.example .env        # valores de desenvolvimento (troque em produção)
make keys                   # gera secrets/jwt_private.pem e jwt_public.pem (RSA 3072)
make up                     # build + docker compose up -d (≈ 22 containers)
make seed                   # dados de demonstração pela própria API
```

| URL | O quê |
|---|---|
| <http://localhost:8080> | Sistema (frontend + API via gateway) |
| <http://localhost:8080/api/repositorio/monografias/> | API pública do repositório |
| <http://localhost:8080/api/monografias/docs/> | Swagger (troque `monografias` por `auth`, `bancas`, `repositorio`, `notificacoes`, `relatorios`) |
| <http://localhost:8080/admin/> | Django Admin (somente rede institucional — `INSTITUTIONAL_CIDRS`) |
| <http://localhost:15672> | RabbitMQ (`tcc` / `tcc-dev-123`) |
| <http://localhost:8025> | MailHog (e-mails enviados) |

### Usuários de demonstração (senha `Demo@Tcc#2026`, definida em `SEED_SENHA_PADRAO`)

| Papel | E-mail |
|---|---|
| Administrador | `admin@tcc.local` |
| Coordenadores | `prof1@demo.tcc.br` (Sistemas de Informação), `prof2@demo.tcc.br` (Ciência da Computação) |
| Professores/orientadores | `prof3@demo.tcc.br` … `prof10@demo.tcc.br` |
| Alunos | `aluno1@demo.tcc.br` … `aluno20@demo.tcc.br` |
| Membro externo | sem conta: link `/banca/externo/<token>` recebido por e-mail (MailHog) |

## Testes

```bash
make test             # pytest de cada serviço dentro do container (requer `make up`)
make test-integracao  # tcc_common contra o RabbitMQ real (durabilidade, idempotência, DLQ)
make e2e              # fluxo completo contra o gateway (requer `make seed`)
make lint             # ruff + black
cd frontend && npm ci && npm test   # Vitest + Testing Library
```

**Sem Docker** (desenvolvimento): `pip install -e libs/tcc_common -r services/<svc>/requirements-dev.txt pgserver tzdata`
e `python scripts/run_tests_local.py` — sobe um PostgreSQL 16 embutido e roda todos os testes.

## Teste de carga

```bash
make scale            # 3 réplicas do repositório e dos workers
make loadtest         # Locust: 1000 usuários, 5 min (ajuste THROTTLE_ANON/GATEWAY_RATE_* no .env)
```

Sem Docker: `python loadtest/rodar_local.py` (3 cenários; resultados em `loadtest/resultados/`).

## Estrutura

```
libs/tcc_common/      biblioteca compartilhada (JWT, eventos/outbox, cache, auditoria, middleware)
services/<svc>/       6 projetos Django independentes (banco, migrações, API, Dockerfile próprios)
gateway/              Nginx (roteamento, rate limit, proxy_cache, cabeçalhos de segurança)
frontend/             React 18 + Vite + React Router + Axios + Chart.js
loadtest/             Locust (pico de defesa) e executor local
scripts/              init do Postgres, chaves JWT, seed, cliente HTTP, testes locais
tests/e2e/            teste ponta a ponta contra o gateway
docs/                 arquitetura, decisões, eventos, API, segurança, carga, roteiro
```

## Comandos úteis

```bash
make logs                                   # logs JSON (com request_id) de todos os serviços
docker compose exec monografias-service python manage.py verificar_integridade_todas
docker compose exec notificacoes-service python manage.py reenviar_notificacoes
docker compose stop notificacoes-worker     # demonstração de isolamento de falhas
```

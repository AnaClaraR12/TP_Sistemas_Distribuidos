# Sistema Distribuído de Monografias (TCC)

Trabalho de **Sistemas Distribuídos** (Prof. Alessandro Vivas Andrade): cadastro, submissão, avaliação
e publicação de monografias com **6 microsserviços Django**, **RabbitMQ**, **Redis**, **PostgreSQL**
(database por serviço), **API Gateway Nginx** e **frontend React**.

* Arquitetura e fluxos: [docs/ARQUITETURA.md](docs/ARQUITETURA.md) · Decisões: [docs/DECISOES.md](docs/DECISOES.md)
* Eventos: [docs/EVENTOS.md](docs/EVENTOS.md) · API: [docs/API.md](docs/API.md) · Segurança: [docs/SEGURANCA.md](docs/SEGURANCA.md)
* Carga: [docs/TESTE_DE_CARGA.md](docs/TESTE_DE_CARGA.md) · Demonstração: [docs/ROTEIRO_DEMO.md](docs/ROTEIRO_DEMO.md)
* Onde cada requisito do enunciado está e qual teste o prova: [seção abaixo](#requisitos-do-enunciado)

## Pré-requisitos (Linux ou WSL2)

* Docker 24+ com Docker Compose v2, `make`, `openssl`
* Python 3.12+ (só para `make seed`, `make e2e` e `make loadtest` no host: `pip install requests locust pytest`)

## Subir o sistema

```bash
cp .env.example .env        # valores de desenvolvimento (troque em produção)
make keys                   # gera secrets/jwt_private.pem e jwt_public.pem (RSA 3072)
make up                     # build + docker compose up -d (23 containers)
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

## Requisitos do enunciado

Os caminhos de teste são relativos a `services/<serviço>/tests/` (ou `frontend/src/__tests__/`);
`e2e` é `tests/e2e/test_requisitos.py`, que roda contra o sistema completo no Docker.

| Requisito | Onde está | Testes |
|---|---|---|
| Login e senha com django-allauth; senha com Argon2 e política forte | `auth/apps/contas`, `AUTH_PASSWORD_VALIDATORS` | auth `test_autenticacao.py` (`TestLogin`, `TestPoliticaSenha`, `test_hash_argon2`) |
| Papéis: admin, coordenador, professor/orientador, aluno | `contas/models.py` (`Papel`), `tcc_common/auth/permissions.py` | monografias `test_matriz_autorizacao.py`, auth `test_cadastros.py`, tcc_common `test_auth.py` |
| Membro externo por token temporário, sem conta | `bancas/servicos.py` (`gerar_token`, `membro_por_token`) | bancas `test_bancas.py` (`test_token_externo_*`), frontend `bancas.test.jsx` |
| Auditoria das ações | `tcc_common/audit/auditoria.py`, `auth/apps/auditoria` | auth `test_login_registra_auditoria_e_ip`, `test_consumer_audit_registro_centraliza` |
| Página principal e dashboard por tipo de usuário | `contas/dashboard.py`, `frontend/src/pages/Dashboard.jsx` | auth `test_dashboard_config_por_papel`, frontend `dashboard.test.jsx` |
| Rascunho, orientador, upload de PDF, acompanhamento do status | `monografias/views.py`, `servicos.py` | monografias `test_fluxo.py`, `test_upload.py`; frontend `monografias.test.jsx` |
| Só PDF, até 50 MB, SHA-256 e deduplicação | `monografias/arquivos.py` | monografias `test_upload.py`; frontend `componentes.test.jsx` (limite exato) |
| Banca só depois da aprovação do orientador | `bancas/servicos.py` (`exigir_aprovacao_orientador`) | bancas `test_sem_aprovacao_do_orientador_409` |
| Extração de texto assíncrona, pela fila | `repositorio/apps/indexacao/eventos.py` (`on_submetida`) | monografias `test_upload_nao_extrai_texto`, repositorio `test_extracao_assincrona_*` |
| Agendamento: data, local ou link, convites, todos confirmaram, sem conflito de horário | `bancas/servicos.py` (`criar_banca`, `agendar`, `conflitos_de_horario`) | bancas `test_bancas.py` (incl. limite exato e concorrência) |
| Notificação automática a membros e aluno | `notificacoes/eventos.py` (`on_agendada`) | notificacoes `test_banca_agendada_notifica_todos_os_membros_e_aluno` |
| Avaliação (nota e parecer); resultado só com todas; status atualizado | `bancas/servicos.py` (`registrar_avaliacao`, `calcular_resultado`) | bancas `test_resultado_*`, monografias `test_resultado_banca_consumer_idempotente` |
| Publicação automática (aprovada, correção, termo assinado) | `Monografia.tentar_publicar` | monografias `test_publicacao_automatica_completa`, `test_tentar_publicar_com_precondicao_faltando` |
| Busca por título, autor, orientador, curso, ano e palavras-chave | `repositorio/views.py` | repositorio `test_filtros`; frontend `publicas.test.jsx` |
| Hash guardado detecta alteração depois da aprovação | `monografias/servicos.py` (`verificar_integridade`) | monografias `test_integridade_violada`, `test_comando_verificar_integridade_todas` |
| Ações restritas a autenticados; admin só da rede institucional | `IsAutenticado`, `middleware/rede_institucional.py` | auth `test_anonimo_nao_acessa_restritos`, `test_rede_institucional.py` |
| Repositório público sem login | `repositorio/views.py` (`_Publico`) | repositorio `test_publico_sem_autenticacao_e_token_invalido_ignorado` |
| CRUD com as regras de edição e exclusão (inclusive de avaliação, só antes do fechamento do resultado) | viewsets dos serviços, `bancas/servicos.py` (`excluir_avaliacao`) | auth `test_cadastros.py`, monografias `test_excluir_publicada_409`, bancas `test_nao_edita_banca_realizada` e `test_exclusao_*`, frontend `bancas.test.jsx` |
| API REST: públicos (monografias, cursos, orientadores) e restritos | routers de cada serviço | repositorio `test_endpoints_publicos_cursos_e_orientadores`, monografias `test_criar_sem_barra_final_*` |
| Redis: sessões, cache de busca, upload em andamento, rate limit | `SESSION_ENGINE`, `indexacao/cache.py`, `upload_em_andamento:<id>`, `rl:submissao:<id>` | auth `test_sessoes.py`, repositorio `test_cache_*` e `test_redis_fora.py`, monografias `test_submeter_202_evento_e_lock` |
| Eventos: submissão, agendamento, avaliação registrada, publicação | outbox + consumers de cada serviço | `test_eventos.py` (tcc_common) e os testes de consumer de cada serviço; e2e |
| Dashboard: por curso, por orientador, por ano, taxa de aprovação, tempo médio | `relatorios/metricas.py`, `frontend/src/charts/Graficos.jsx` | relatorios `test_relatorios.py`, frontend `dashboard.test.jsx` |
| Telas: submissão, aprovação, agendamento, avaliação, pesquisa pública | `frontend/src/pages` | frontend `monografias.test.jsx`, `bancas.test.jsx`, `publicas.test.jsx` |
| Histórico: quem, o quê, quando | `tcc_common/audit/historico.py` | monografias `test_editar_rascunho_e_historico`, auth `test_historico_registra_quem_alterou`, frontend `componentes.test.jsx` |
| Escalabilidade (cache, filas, réplicas) | gateway, `make scale` | `docs/TESTE_DE_CARGA.md` |

Números da última verificação: 345 testes Python passando (os 3 de integração com RabbitMQ real
passam com `make test-integracao`), 95 testes no frontend, 83 testes ponta a ponta contra o sistema
completo, cobertura entre 91% e 95% por serviço.

## Comandos úteis

```bash
make logs                                   # logs JSON (com request_id) de todos os serviços
docker compose exec monografias-service python manage.py verificar_integridade_todas
docker compose exec notificacoes-service python manage.py reenviar_notificacoes
docker compose stop notificacoes-worker     # demonstração de isolamento de falhas
```

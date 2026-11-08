# Relatório de execução por fase

Formato da seção 9 do roteiro (resumo, arquivos, como executar, como testar + resultado real,
critérios de aceite, decisões, pendências). **Ambiente desta entrega:** Windows 11 sem Docker/WSL;
validação com PostgreSQL 16 embutido (`pgserver`), Redis simulado (`fakeredis`) e Node 26.
Itens que exigem Docker/RabbitMQ real estão marcados com **🟡 (pronto, não executado aqui)**.

Comando que reproduz todos os testes Python sem Docker: `python scripts/run_tests_local.py`.

**Total desta entrega: 309 testes Python passando (3 pulados por exigirem RabbitMQ real) + 10 testes do frontend; ruff e black sem pendências; build de produção do frontend OK.**

---

## Fase 0 — Infraestrutura e esqueleto

1. **Resumo.** Monorepo conforme a seção 5; `docker-compose.yml` com 23 contêineres (Postgres 16, Redis 7,
   RabbitMQ 3.13-management, MailHog, 6 serviços × API/outbox/worker, cron de integridade, gateway, frontend),
   volumes nomeados, chaves RSA via Docker *secrets*, `init-databases.sql` (6 databases + `unaccent`/`pg_trgm`)
   e `init-roles.sh` (um usuário Postgres por serviço). Cada serviço é um projeto Django independente com
   `/health/` e `/ready/`, Dockerfile, Gunicorn e entrypoint.
2. **Arquivos.** `docker-compose.yml`, `docker-compose.override.yml`, `.env.example`, `Makefile`, `.gitignore`,
   `.gitattributes`, `pyproject.toml`, `scripts/{init-databases.sql,init-roles.sh,generate_jwt_keys.sh,dev_local_postgres.py}`,
   `services/*/{Dockerfile,manage.py,entrypoint.sh,gunicorn.conf.py,requirements*.txt,config/*}`, `libs/tcc_common/{settings_base.py,api/*}`.
3. **Executar.** `cp .env.example .env && make keys && make up`.
4. **Testar.** `curl localhost:8080/api/<svc>/health/` (×6). Localmente: healthchecks cobertos por
   `libs/tcc_common/tests/test_infra.py::test_health_e_ready` (✅). O YAML do compose foi validado (23 serviços, âncoras resolvidas).
5. **Critérios.** `docker compose up -d` + 6 health 200 — 🟡 · RabbitMQ :15672 / MailHog :8025 — 🟡 (portas mapeadas) ·
   `make test` roda — 🟡 no Docker; ✅ equivalente local `scripts/run_tests_local.py`.
6. **Decisões.** Usuário Postgres por serviço (ADR-03); settings compartilhados em `tcc_common.settings_base`. Registradas em `docs/DECISOES.md`.
7. **Pendências.** Subir o compose numa máquina Linux com Docker. **Próxima:** Fase 3.

## Fase 3 — Biblioteca de eventos (`tcc_common.events`)

1. **Resumo.** Envelope padrão com `schema_version` e catálogo de campos obrigatórios validado na publicação;
   tabelas `outbox`/`evento_processado` (app Django compartilhado); `publish_outbox` com `FOR UPDATE SKIP LOCKED`,
   publisher confirms e `delivery_mode=2`; topologia idempotente (`tcc.events` topic, `tcc.dlx`, filas
   `<svc>.<rk>`, `.retry.1..3` com TTL 10 s/60 s/5 min, `.dlq`); `BaseConsumer` com prefetch, idempotência,
   ack após commit, retry com backoff, `falha_definitiva()` e DLQ; máscara de segredos no outbox.
2. **Arquivos.** `libs/tcc_common/tcc_common/events/*`, `libs/tcc_common/tests/test_eventos.py`, `test_integracao_rabbitmq.py`.
3. **Executar.** Containers `<svc>-outbox` (`publish_outbox`) e `<svc>-worker` (`run_consumer`).
4. **Testar.** `cd libs/tcc_common && pytest` → **resultado real: 31 passaram / 0 falharam / 3 pulados (integração com RabbitMQ real); cobertura 63 % (a lib inclui código de I/O do broker e o plugin de testes)**.
   Integração com RabbitMQ real: `make test-integracao` (3 testes, pulados aqui por falta de broker).
5. **Critérios.** Durabilidade (10 eventos com consumer fora) — 🟡 teste escrito · mesmo `event_id` não duplica — ✅
   (`test_processar_evento_idempotente`) · mensagem veneno → DLQ após tentativas — ✅ lógica (`test_mensagem_veneno_vai_para_dlq…`), 🟡 broker real.
6. **Decisões.** ADR-02 (outbox), ADR-06 (tabelas concretas na lib), ADR-09 (máscara de token), ADR-10 (contratos).
7. **Pendências.** Rodar `make test-integracao`. **Próxima:** Fase 1.

## Fase 1 — auth-service

1. **Resumo.** `User` customizado (UUID, login por e-mail, papel, `ultimo_login_ip`) antes da 1ª migração;
   django-allauth com cadastro público desabilitado e templates em pt-BR; Argon2 + política de senha (12+, complexidade);
   bloqueio 5 falhas/15 min no Redis; sessões no Redis; grupos por *data migration*; JWT RS256 (`token`, `refresh`
   com rotação, `logout` com blacklist de `jti`, `me`, `dashboard-config`, JWKS); CRUD de Curso/Professor/Aluno
   criando o `User` com e-mail "defina sua senha" e publicando `cadastro.*`; auditoria (sinais de login +
   CRUD + consumer de `audit.registro`); middleware de rede institucional em `/admin/` e `/api/auth/admin/**`.
2. **Arquivos.** `services/auth/apps/{contas,academico,auditoria}/*`, `config/settings/base.py`, `config/urls.py`, `templates/`, `tests/*`.
3. **Executar.** `make up`; admin inicial: `docker compose exec auth-service python manage.py garantir_admin --email … --senha …`.
4. **Testar.** `cd services/auth && pytest` → **resultado real: 54 passaram / 0 falharam; cobertura 94 %**.
5. **Critérios.** Login dos 4 papéis e obtenção de JWT — ✅ (`TestLogin`, `test_claims_de_aluno`) · outro serviço valida o JWT
   sem chamar o auth — ✅ (`test_validacao_por_jwks_sem_chave_local`: 1 chamada ao JWKS, depois cache) · `/admin/` fora
   dos CIDRs → 403, dentro → 200 — ✅ (`test_rede_institucional.py`) · senha fraca rejeitada e hash `argon2$` — ✅.
6. **Decisões.** Bloqueio via backend próprio no Redis (sem django-axes); revogação JWT falha fechada (ADR-05).
7. **Pendências.** Nenhuma funcional. **Próxima:** Fase 2.

## Fase 2 — monografias-service

1. **Resumo.** Modelos do Anexo A com `UniqueConstraint` parcial de SHA-256 e `CheckConstraint` de publicação;
   máquina de estados com métodos de domínio e proteção no `save()`; CRUD com escopo por papel e filtros
   (`?busca=` insensível a acento); upload com as 9 validações na ordem pedida; `submeter` 202 com outbox;
   aprovação/rejeição do orientador com snapshot de integridade; verificação de integridade (endpoint + comando
   diário); documentos complementares; `tentar_publicar()`; endpoint interno de streaming; histórico.
2. **Arquivos.** `services/monografias/apps/monografias/{models,estados,arquivos,servicos,views,serializers,filtros,eventos}.py`, comando `verificar_integridade_todas`, `tests/*`.
3. **Executar.** `make up` (API + outbox + worker + cron).
4. **Testar.** `cd services/monografias && pytest` → **resultado real: 118 passaram / 0 falharam (inclui 64 da matriz de autorização); cobertura 95 %**.
5. **Critérios.** Fluxo rascunho → upload → submeter → aprovar via API — ✅ (`test_fluxo.py`) · `.txt` renomeado rejeitado,
   > 50 MB rejeitado, reenvio durante processamento 409 — ✅ · upload/submissão de 20 MB < 1 s — ✅ (medido: upload 0,056 s,
   submissão 0,004 s) · evento `monografia.submetida` no RabbitMQ — ✅ gravado no outbox; 🟡 visualização no painel.
6. **Decisões.** Normalização de acentos em coluna `busca_normalizada` (ADR-04); versão corrigida vira o arquivo oficial (ADR-11).
7. **Pendências.** Nenhuma funcional. **Próxima:** Fase 5.

## Fase 5 — repositorio-service

1. **Resumo.** `DocumentoIndexado` com colunas normalizadas, `SearchVectorField` e índices GIN/B-tree (+ trigram quando
   `pg_trgm` existe); consumer de `monografia.submetida` (download em streaming, pdfplumber página a página com limite
   de páginas/tempo, fallback pypdf, PDF sem texto não é erro, corrompido → `extracao_falhou`); consumer de
   `monografia.publicada` (público, cópia verificada do PDF, reextração se a versão mudou, `INCR busca:versao`);
   API pública com filtros, ranking, destaque, download com verificação de hash e contador; cache-aside com
   anti-stampede e `X-Cache`; `Cache-Control` + ETag; throttling anônimo.
2. **Arquivos.** `services/repositorio/apps/indexacao/{models,extracao,eventos,cache,views}.py`, migração `0002_extensoes_trigram`, `tests/*`.
3. **Executar.** `make up`; escala: `make scale`.
4. **Testar.** `cd services/repositorio && pytest` → **resultado real: 32 passaram / 0 falharam; cobertura 92 %**.
5. **Critérios.** Só aparece após `monografia.publicada` — ✅ (`test_extracao_assincrona_indexa_sem_publicar`) · 2ª busca
   `X-Cache: HIT` mais rápida — ✅ (MISS 3,5 ms × HIT 0,5 ms no teste; ver carga) · palavra só no corpo do PDF encontra — ✅.
6. **Decisões.** Cópia própria do PDF publicado (resiliência), normalização em Python (ADR-04, ADR-08).
7. **Pendências.** `EXPLAIN ANALYZE` com volume real no Docker. **Próxima:** Fase 6.

## Fase 6 — notificacoes-service

1. **Resumo.** `Notificacao` com unicidade (evento, destinatário, tipo); 11 consumers com templates em português
   para todos os eventos da tabela da fase; destinatários via read models; envio com 3 tentativas e backoff
   exponencial; falha persistente fica `falhou` e é reprocessada por `reenviar_notificacoes`; alertas in-app.
2. **Arquivos.** `services/notificacoes/apps/notificacoes/{models,envio,eventos,templates_email,views}.py`, `tests/*`.
3. **Executar.** `make up`; e-mails em <http://localhost:8025>.
4. **Testar.** `cd services/notificacoes && pytest` → **resultado real: 14 passaram / 0 falharam; cobertura 91 %**.
5. **Critérios.** Agendamento → e-mail a todos os membros e ao aluno — ✅ (`test_banca_agendada_notifica_todos_os_membros_e_aluno`), 🟡 no MailHog ·
   aluno recebe e-mail na publicação — ✅ (`test_publicacao_notifica_aluno_com_link_publico`).
6. **Decisões.** ADR-12 (sem reenvio em massa ao falhar). **Pendências.** Nenhuma. **Próxima:** Fase 4.

## Fase 4 — bancas-service

1. **Resumo.** Modelos com `CheckConstraint` local XOR link e unicidades; criação (etapa 1) com validação de aprovação
   via read model + fallback HTTP interno, orientador incluído automaticamente, mínimo de 3 membros, convites e token
   externo (`token_urlsafe(32)`, só SHA-256, expira em data + 7 dias); confirmação interna/externa (rate limit por IP);
   agendamento (etapa 2) com todas as confirmações + conflito de horário sob `pg_advisory_xact_lock`; edição
   (novo horário exige reconfirmação), cancelamento com revogação, realização; avaliações (0–10 com 1 casa, parecer ≥ 50,
   unicidade, edição até o fechamento); cálculo assíncrono, idempotente e com lock; acesso externo com URL assinada
   para o PDF; auditoria de geração/uso/revogação de token; histórico.
2. **Arquivos.** `services/bancas/apps/bancas/{models,servicos,views,serializers,eventos}.py`, `tests/*`.
3. **Executar.** `make up`.
4. **Testar.** `cd services/bancas && pytest` → **resultado real: 49 passaram / 0 falharam (inclui concorrência real com 2 threads); cobertura 91 %**.
5. **Critérios.** Fluxo 2 internos + 1 externo termina em `banca.resultado_calculado` e muda o status da monografia — ✅ por
   partes (bancas: `test_resultado_aprovada_media`; monografias: `test_resultado_banca_consumer_idempotente`), 🟡 ponta a ponta no E2E ·
   não calcula com 2 de 3 — ✅ · token externo não acessa nada fora da sua banca — ✅ (`test_token_externo_acessa_somente_sua_banca`).
6. **Decisões.** ADR-07 (advisory lock). **Pendências.** Nenhuma funcional. **Próxima:** Fase 7.

## Fase 7 — relatorios-service

1. **Resumo.** `FatoMonografia` mantido por consumers idempotentes (upsert) de `monografia.*`, `banca.resultado_calculado` e
   `cadastro.*`; 6 endpoints com agregação no banco (`Count`, `Avg` de duração, `ExtractYear`), escopo por papel e cache
   Redis de 60 s invalidado por eventos.
2. **Arquivos.** `services/relatorios/apps/relatorios/{models,metricas,eventos,views}.py`, `tests/*`.
3. **Executar.** `make up`; dashboard no frontend (coordenador/admin).
4. **Testar.** `cd services/relatorios && pytest` → **resultado real: 11 passaram / 0 falharam; cobertura 90 %**.
5. **Critérios.** Números batem com dados controlados (conferência manual: SI = 4 monografias, taxa 2/3 = 66,67 %, tempo médio
   (30+10+20+4)/4 = 16 dias) — ✅ (`test_relatorios.py`); com o seed — 🟡.
6. **Decisões.** Divisão por zero retorna `null`. **Pendências.** Nenhuma. **Próxima:** Fase 8.

## Fase 8 — API Gateway (Nginx)

1. **Resumo.** Upstreams com `resolve` (escala com `--scale`), roteamento por prefixo, `X-Request-ID`/`X-Real-IP`/`X-Forwarded-For`,
   `client_max_body_size 55m` só nas rotas de upload, `limit_req` no repositório e no login, gzip, `proxy_cache` 30 s com
   `proxy_cache_lock`, cabeçalhos de segurança e CSP; router com barra final opcional nos serviços.
2. **Arquivos.** `gateway/{nginx.conf,templates/default.conf.template,Dockerfile}`, `tcc_common/api/routers.py`, `docs/API.md`.
3. **Executar.** Incluído no `make up` (porta 8080).
4. **Testar.** Exemplos do enunciado sem barra final — ✅ (`test_criar_sem_barra_final_e_dados_do_jwt`, busca `?busca=sistemas+distribuidos`).
   Sintaxe do Nginx — 🟡 (`docker compose run --rm gateway nginx -t`).
5. **Critérios.** Toda a API via `:8080/api/...` — 🟡 · Swagger de cada serviço com Bearer — ✅ configurado (`/api/<svc>/docs/`), 🟡 visual.
6. **Decisões.** `/api/bancas/externo/*` usa token próprio (equivale ao `/api/banca-externa/**` do roteiro). **Próxima:** Fase 9.

## Fase 9 — Frontend (React + Vite)

1. **Resumo.** React 18 + Router + Axios (Bearer, refresh automático em 401, tokens em memória e refresh em `sessionStorage`)
   + Chart.js; páginas públicas (início, pesquisa com filtros/debounce 400 ms/paginação/destaque seguro, detalhe, download),
   login, dashboard por papel (linha do tempo do aluno, pendências do orientador, KPIs e 6 gráficos), monografia (edição,
   upload com progresso, submissão, aprovação/rejeição, documentos, validação de termo/correção, integridade, histórico),
   bancas (agendamento com exibição de conflitos, confirmações, avaliação), membro externo por token, cadastros, auditoria,
   usuários, notificações. Build multi-stage servido por Nginx.
2. **Arquivos.** `frontend/src/**`, `frontend/{package.json,vite.config.js,Dockerfile,nginx-spa.conf}`.
3. **Executar.** Incluído no `make up`; dev: `cd frontend && npm run dev` (proxy para :8080).
4. **Testar.** `npm test` → **resultado real: 10 passaram / 0 falharam** (upload, avaliação, validações, XSS); `npm run build` ✅ (147 KB gzip).
5. **Critérios.** Fluxo completo só pela interface — 🟡 (telas implementadas; roteiro em `docs/ROTEIRO_DEMO.md`) · rotas protegidas
   redirecionam para login; público pesquisa sem login — ✅ (`RotaProtegida`, rotas públicas).
6. **Decisões.** Sem TypeScript (exigência); destaque renderizado sem `innerHTML`. **Próxima:** Fase 10.

## Fase 10 — Auditoria, histórico e segurança

1. **Resumo.** `Historico()` em todos os models de negócio guardando o UUID do usuário do JWT; `/historico/` com diff campo a campo
   em Monografia, Banca, Avaliação, Curso, Professor, Aluno; `audit.registro` centralizado; checklist de segurança; matriz de
   autorização parametrizada (papel × endpoint, incluindo anônimo).
2. **Arquivos.** `tcc_common/audit/*`, `docs/SEGURANCA.md`, `services/monografias/tests/test_matriz_autorizacao.py`.
3. **Testar.** Matriz: **64 passaram / 0 falharam**.
4. **Critérios.** Editar rascunho gera histórico com o usuário correto — ✅ (`test_editar_rascunho_e_historico`) · nenhum endpoint
   restrito responde 200 a anônimo — ✅.
5. **Pendências.** Rodar `pip-audit`/`npm audit` (registrado no checklist). **Próxima:** Fase 11.

## Fase 11 — Escalabilidade e teste de carga

1. **Resumo.** Serviços stateless; `--scale` com upstream dinâmico e *competing consumers*; Gunicorn `2*CPU+1` gthread; 3 camadas de
   cache; Locust com mistura 80/15/5 e Zipf; executor local que mede 3 cenários (sem cache × com cache × 3 réplicas).
2. **Arquivos.** `loadtest/{locustfile.py,rodar_local.py,popular_base.py,README.md}`, `loadtest/resultados/*`, `docs/TESTE_DE_CARGA.md`.
3. **Testar.** `python loadtest/rodar_local.py --usuarios 1000 --duracao 60`.
4. **Resultado real** (máquina local, 3 000 documentos): ver tabela em `docs/TESTE_DE_CARGA.md` — 400 usuários: sem cache 138 req/s e p95 1,9 s; com cache 307 req/s e p95 94 ms (95 % HIT); 3 réplicas p95 25 ms; 0 % de erros. Rampa a 1 000: sem cache satura (p95 6,6 s, 0 erros); com cache e 3 réplicas estável até ~620 usuários (371 req/s, p95 51 ms) — acima de ~700 conexões o loopback do Windows passa a recusar conexões (limite do ambiente local, documentado).
5. **Critérios.** Relatório com números reais e conclusão — ✅ · matar um serviço não derruba o resto — 🟡 (roteiro de resiliência
   documentado; por construção, a busca pública não depende de RabbitMQ, notificações nem monografias).
6. **Pendências.** Repetir no Docker com Nginx `proxy_cache` e Postgres em contêiner. **Próxima:** Fase 12.

## Fase 12 — E2E, documentação e entrega

1. **Resumo.** Seed pela própria API (admin, 2 coordenadores, 10 professores, 20 alunos, ~40 monografias, 5 bancas: 3 publicadas,
   1 aguardando termo, 1 reprovada; convites externos lidos do MailHog); E2E automatizado contra o gateway (fluxo feliz em 9
   passos + negativos); README, ARQUITETURA (C4 + sequências), EVENTOS, DECISOES, API, SEGURANCA, CHECKLIST, ROTEIRO_DEMO; git com
   commits por fase e tag `v1.0.0`.
2. **Arquivos.** `scripts/{seed_demo.py,tcc_cliente.py,run_tests_local.py}`, `tests/e2e/test_fluxo_completo.py`, `docs/*`, `README.md`, `CHANGELOG.md`.
3. **Executar.** `make up && make seed && make e2e`.
4. **Testar.** E2E — 🟡 (pulado automaticamente sem gateway). Gerador de PDF do seed validado com pdfplumber — ✅.
5. **Critérios.** clone + `.env` + `make up` + `make seed` < 10 min — 🟡 · E2E verde — 🟡 · checklist 100 % — ✅ itens implementados com
   evidência (`docs/CHECKLIST.md`), com marcação explícita do que depende do Docker.
6. **Pendências.** Executar `make up && make seed && make e2e` numa máquina Linux com Docker e anexar as evidências.

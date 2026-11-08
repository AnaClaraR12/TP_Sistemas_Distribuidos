# Changelog

Formato baseado em *Keep a Changelog*; versões semânticas.

## [1.0.0] — 2026-11-08

### Fase 0 — Infraestrutura
- Monorepo, `docker-compose.yml` (Postgres 16, Redis 7, RabbitMQ 3.13, MailHog, 6 serviços × API/outbox/worker, gateway, frontend), override de desenvolvimento, `.env.example`, `Makefile`, chaves RSA via Docker secrets, `init-databases.sql` + usuário Postgres por serviço.
### Fase 3 — Eventos
- `tcc_common.events`: envelope com `schema_version`, catálogo validado, outbox transacional, `publish_outbox` (`SKIP LOCKED`), publisher com confirms, `BaseConsumer` (idempotência, ack pós-commit, retry 10 s/60 s/5 min, DLQ), máscara de segredos.
### Fase 1 — auth-service
- User UUID/e-mail/papel, django-allauth (cadastro público desabilitado), Argon2 + política de senha, bloqueio por tentativas, sessões no Redis, grupos por data migration, JWT RS256 (token/refresh/logout/me/JWKS), CRUD de cursos/professores/alunos com eventos `cadastro.*`, auditoria centralizada, rede institucional, `dashboard-config`.
### Fase 2 — monografias-service
- Máquina de estados protegida, upload validado (formato, 50 MB em streaming, SHA-256, dedup, lock, rate limit), submissão 202, aprovação/rejeição do orientador, integridade (sob demanda e diária), documentos complementares, publicação automática, endpoint interno de streaming, histórico.
### Fase 4 — bancas-service
- Agendamento em 2 etapas, token externo (hash + expiração + revogação), conflito de horário com advisory lock, avaliações com edição até o fechamento, cálculo assíncrono e idempotente do resultado.
### Fase 5 — repositorio-service
- Extração assíncrona (pdfplumber/pypdf), FTS com pesos e índice GIN, busca pública com filtros, destaque, cache Redis com anti-stampede e invalidação por versão, `Cache-Control`/ETag, cursos/orientadores públicos, cópia verificada do PDF publicado.
### Fase 6 — notificacoes-service
- E-mails por evento (templates em português), idempotência, retry com backoff, alertas in-app.
### Fase 7 — relatorios-service
- `FatoMonografia` por eventos, métricas agregadas no banco, escopo por papel, cache de 60 s invalidado por eventos.
### Fase 8 — Gateway
- Nginx com upstreams escaláveis (`resolve`), rate limit, `proxy_cache`, X-Request-ID, limites de upload por rota, cabeçalhos de segurança/CSP.
### Fase 9 — Frontend
- React 18 + Vite: páginas públicas, login, dashboards por papel com Chart.js, fluxo do aluno (upload com progresso), orientador, coordenador (agendamento com conflitos, cadastros, auditoria), membro interno/externo (avaliação), histórico; testes Vitest.
### Fases 10–12
- Matriz de autorização (64 casos), checklist de segurança, teste de carga (Locust + executor local), seed pela API, E2E contra o gateway, documentação e roteiro de demonstração.

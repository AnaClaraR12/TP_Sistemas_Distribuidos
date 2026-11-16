# Decisões de arquitetura (ADRs curtas) e premissas

## Pontos que o enunciado deixa em aberto e como foram decididos

| # | Premissa | Onde está |
|---|---|---|
| P1 | Aluno/Professor/Curso ficam no **auth-service**; os demais mantêm *read models* via `cadastro.*` | `services/auth/apps/academico`, `*Ref` nos serviços |
| P2 | Cadastro público desabilitado (contas criadas por admin/coordenador) | `ContaAdapter.is_open_for_signup = False` |
| P3 | Upload mantém `rascunho`; só `submeter` muda para `em_avaliacao`; aprovação do orientador é campo próprio | `Monografia.submeter()`, `aprovacao_orientador` |
| P4 | Agendamento em 2 etapas (`em_organizacao` → `agendada` após todas as confirmações) | `servicos.criar_banca` / `servicos.agendar` |
| P5 | Aprovada se média ≥ 6,0 **e** maioria não-“reprovado”; qualquer “com ressalvas” exige correção | `servicos.calcular_resultado` (`NOTA_MINIMA` por env) |
| P6 | Banca mínima de 3 membros (orientador incluído automaticamente); 2 h padrão | `BANCA_MIN_MEMBROS`, `BANCA_DURACAO_PADRAO_MIN` |
| P7 | Publicação exige aprovada + correção validada (se houver) + termo validado + integridade OK | `Monografia.pendencias_publicacao()` |
| P8 | RabbitMQ (não Kafka); Postgres FTS (não Elasticsearch) | ADR-01, ADR-04 |
| P9 | Arquivos em volume Docker compartilhado; MinIO/S3 como evolução | ADR-08 |
| P10 | Membro externo sem `User`; token com hash, expira em data da banca + 7 dias, revogado ao fechar | `MembroBanca.token_hash`, `_revogar_tokens` |
| P11 | Rede institucional por `INSTITUTIONAL_CIDRS`; `X-Real-IP` só é confiável vindo do gateway | `InstitutionalNetworkMiddleware` |

## ADRs

**ADR-01 — RabbitMQ (exchange *topic*) em vez de Kafka.** O problema é de *mensageria de tarefas*
(extração, notificação, cálculo) com roteamento por tipo de evento, retry e DLQ — recursos nativos do
RabbitMQ. Kafka brilharia em *event sourcing*/reprocessamento massivo, que não é requisito.

**ADR-02 — Transactional Outbox.** Gravar o evento na tabela `outbox` na MESMA transação do dado evita
o problema de "dual write" (salvar no banco e falhar ao publicar). O `publish_outbox` usa
`SELECT … FOR UPDATE SKIP LOCKED` (permite várias réplicas). Entrega é *at-least-once*; por isso todo
consumer é idempotente (`evento_processado.event_id` único) e faz `ack` só após o commit.

**ADR-03 — Database-per-service com usuário por serviço.** Um único container Postgres (simplicidade de
operação), mas cada serviço tem database **e usuário próprios** (`scripts/init-roles.sh`, `REVOKE … FROM
PUBLIC`): um serviço não consegue ler o banco de outro nem por engano. Joins entre domínios são
substituídos por *read models* alimentados por eventos.

**ADR-04 — Busca com PostgreSQL Full-Text Search.** `SearchVector` com pesos (A título, B palavras-chave
e resumo, C corpo do PDF), `websearch_to_tsquery`, `ts_rank`, `ts_headline` e índice GIN. Evita operar um
Elasticsearch para um volume de documentos modesto. **Acentos:** o texto é normalizado em Python
(`tcc_common.texto.normalizar`) antes de gerar o `tsvector` e a consulta — funciona mesmo sem a extensão
`unaccent` (que também é criada no Docker para uso futuro e para `pg_trgm`).

**ADR-05 — JWT RS256 com validação local.** O auth-service assina com a chave privada; os demais validam
com a chave pública (secret Docker ou JWKS cacheado no Redis por 1 h) — nenhuma chamada ao auth por
requisição. Logout/rotação de refresh usam *blacklist* de `jti` no Redis com TTL até o `exp`. Se o Redis
estiver indisponível a checagem de revogação **falha fechada** (configurável por `JWT_REVOGACAO_FAIL_OPEN`).

**ADR-06 — Tabelas `outbox`/`evento_processado` concretas na lib compartilhada.** Em vez de um model
abstrato herdado por cada serviço, `tcc_common.events` é um app Django com migrações próprias; como
cada serviço tem seu banco, cada um ganha suas próprias tabelas. Menos código repetido.

**ADR-07 — Lock de conflito de horário com `pg_advisory_xact_lock`.** Duas requisições concorrentes que
agendam bancas diferentes com um membro em comum seriam uma *race condition* clássica. Antes de checar
sobreposição, a transação adquire um advisory lock por membro (`prof:<id>` e `email:<email>`, em ordem
para evitar deadlock). Coberto por teste com 2 threads simultâneas.

**ADR-08 — Armazenamento de arquivos em volume.** `media_monografias` é compartilhado entre API, worker e
cron do monografias-service; o repositorio-service guarda **sua própria cópia** do PDF publicado
(`media_repositorio`), verificando o SHA-256 — os downloads públicos continuam funcionando mesmo se o
monografias-service cair. **Limitação:** volumes locais não escalam entre hosts; a evolução é MinIO/S3
(o código usa `default_storage`, então a troca é de configuração).

**ADR-09 — Token do membro externo nunca persistido em claro.** O banco guarda o SHA-256; o token só
existe na mensagem `banca.convite_enviado`. Após publicar, o `publish_outbox` mascara o campo `token` no
payload do outbox (`CAMPOS_SENSIVEIS`) e o notificacoes-service armazena o corpo do e-mail com o token
substituído por `***`.

**ADR-10 — Contratos de eventos validados nos dois lados.** `tcc_common.events.schemas` define os campos
obrigatórios de cada tipo; `criar_envelope` valida na publicação e os testes dos consumers usam o mesmo
helper — produtor e consumidor não divergem silenciosamente.

**ADR-11 — Versão corrigida vira o arquivo oficial.** Quando o orientador valida a versão corrigida, ela
passa a ser o `arquivo` da monografia com novo snapshot `arquivo_sha256_aprovado` (é a única exceção à
imutabilidade pós-aprovação). O repositório reextrai o texto se o hash publicado diferir do indexado.

**ADR-12 — Notificação com retry no consumer, sem reprocessar e-mails já enviados.** Cada envio tenta 3×
com backoff exponencial; persistindo a falha, a notificação fica `falhou` (sem lançar exceção, para não
reenviar aos destinatários que já receberam) e o comando `reenviar_notificacoes` a reprocessa.

## Simplificações conscientes

* Coordenador consulta a auditoria completa (o roteiro sugere filtrar "por curso"; os registros de
  auditoria não carregam curso — evolução simples: adicionar `curso_id` ao evento `audit.registro`).
* `marcar-realizada` é manual (comando automático por horário é opcional no roteiro).
* O e-mail "defina sua senha" usa o fluxo de reset do allauth (link de uso único).
* Django 6.1 marca `EMAIL_*` como depreciado em favor de `MAILERS` (remoção prevista para 2028); mantivemos
  `EMAIL_*` por compatibilidade com o allauth.

## Ambiente de desenvolvimento sem Docker (registro desta entrega)

A máquina usada para construir esta entrega **não tinha Docker/WSL**. Todo o código foi validado com:
PostgreSQL 16 embutido (`pgserver`, com tzdata copiado — `scripts/dev_local_postgres.py`), Redis falso
(`fakeredis`, em memória nos testes e em TCP no teste de carga) e testes unitários/contrato dos consumers.
O `docker compose`, o RabbitMQ real e o E2E contra o gateway estão prontos, mas **devem ser executados
numa máquina Linux com Docker** (ver README).

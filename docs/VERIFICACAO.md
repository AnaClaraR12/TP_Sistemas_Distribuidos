# Verificação do enunciado contra o sistema real

O workflow [`.github/workflows/e2e.yml`](../.github/workflows/e2e.yml) sobe **os 23 contêineres reais**
(`docker compose up --wait`) num runner Linux do GitHub Actions, popula o sistema **pela própria API**
(`scripts/seed_demo.py`) e executa `tests/e2e/` contra o gateway (`http://localhost:8080`), inspecionando
também Redis, RabbitMQ (API de gerenciamento), Postgres e MailHog.

**Resultado:** 83 de 83 testes passando (execução `42510052964`), além do CI de unidade
(lint, 6 serviços, `tcc_common` com 3 testes de integração em RabbitMQ real, frontend).

## Requisito do PDF → teste que o comprova (sistema em Docker)

### Requisitos gerais

| Requisito | Teste E2E (`tests/e2e/test_requisitos.py`) |
|---|---|
| Django + DRF + PostgreSQL (um database por serviço) | `TestMicrosservicos::test_um_banco_por_servico`, `test_servico_nao_acessa_banco_de_outro` |
| Redis (cache e controle de submissões) | `test_cache_redis_hit_miss_e_chave_busca`, `test_upload_em_andamento_bloqueia_reenvio`, `TestRateLimit` |
| RabbitMQ (fila de eventos) | `TestFilaDeEventos` (7 filas com consumidor, mensagens confirmadas, DLX/DLQ/retry; exchange *topic*) |
| Extração de texto de PDF | `test_submissao_assincrona`, `test_pesquisavel_por_cada_criterio[texto do PDF]` |
| Frontend em JavaScript | `TestFrontend` (página, rotas da SPA, bundle, CSP) |
| Linux | todo o workflow roda em `ubuntu-latest` com Docker Compose |

### Parte 1 — Autenticação

| Requisito | Teste |
|---|---|
| django-allauth, login e senha | `test_login_e_senha_por_papel` (4 papéis), `test_senha_errada_401`, `test_cadastro_publico_desabilitado` |
| Papéis + membro externo por token temporário | `test_login_e_senha_por_papel`, `test_token_externo_restrito`, `test_avaliacao_bloqueada_apos_fechamento_e_token_revogado` |
| Controle de acesso por permissões | `TestControleDeAcesso::test_permissoes_por_papel`, `test_anonimo_nao_acessa_restritos` |
| Criptografia e política de senhas | `test_senhas_criptografadas_com_argon2_e_politica`, `test_bloqueio_apos_tentativas` |
| Registro de auditoria | `test_auditoria_centralizada_de_varios_servicos` |
| Página principal e dashboard por tipo de usuário | `test_pagina_principal`, `test_dashboard_personalizado_por_tipo` |

### Parte 1 — Submissão, banca, publicação, integridade, CRUD

| Requisito | Teste |
|---|---|
| Rascunho com orientador, upload, acompanhamento de status | `test_rascunho_com_orientador`, `test_upload_com_sha256`, `test_acompanhamento_de_status_e_aprovacao` |
| Somente PDF | `test_somente_pdf` (.txt renomeado → 415) |
| Tamanho máximo 50 MB | `test_tamanho_maximo_50mb` (51 MB → 413, passando pelo gateway) |
| SHA-256 (deduplicação) | `test_upload_com_sha256`, `test_deduplicacao_por_hash` |
| Banca só após aprovação do orientador | `test_banca_bloqueada_sem_aprovacao_do_orientador` |
| Extração assíncrona via fila | `test_submissao_assincrona` (202 em < 1 s, `texto_extraido=false` na resposta, lock liberado pelo evento) |
| Agendamento: data, local ou link, membros (incl. externo) | `test_agendamento_e_confirmacoes`, `test_conflito_de_horario` (banca remota com link) |
| Validações: aprovação, todos confirmaram, sem conflito | `test_agendamento_e_confirmacoes` (409 pendentes), `test_conflito_de_horario` (409 com o conflito) |
| Notificação automática a membros e aluno | `test_notificacao_a_todos_os_membros_e_aluno` (MailHog) |
| Avaliação; resultado só com todas; atualiza status | `test_resultado_somente_com_todas_as_avaliacoes` (2 de 3 não calcula; média 9,00; status muda) |
| Publicação automática (aprovada + correção + termo) | `test_publicacao_automatica_apos_termo`, `test_ressalvas_exigem_versao_corrigida` |
| Busca por título, autor, orientador, curso, ano, palavras-chave | `test_pesquisavel_por_cada_criterio` (8 critérios) |
| Hash armazenado e detecção de alteração | `TestIntegridade` (arquivo adulterado no contêiner → violação, auditoria crítica, e-mail ao admin) |
| Ações restritas a autenticados; admin só da rede institucional | `test_area_admin_somente_rede_institucional`, `test_spoof_de_ip_nao_burla_rede_institucional` |
| Leitura pública sem autenticação | `test_leitura_publica_sem_autenticacao_e_download_integro`, `test_endpoints_publicos_json` |
| CRUD alunos, professores, cursos | `TestCrudCadastros` (com propagação por eventos e e-mail "defina sua senha") |
| CRUD monografias, bancas, avaliações | `TestSubmissao`, `test_edicao_de_banca_nao_realizada`, `test_cancelamento_e_exclusao_de_banca`, `test_resultado_somente_com_todas_as_avaliacoes` |
| Edição só de rascunho, banca não realizada, avaliação pelo avaliador antes do fechamento | `test_edicao_em_rascunho_e_historico`, `test_avaliacao_bloqueada_apos_fechamento_e_token_revogado`, `test_publicada_nunca_excluida_nem_editada` |
| Exclusão só por autorizados e nunca de publicadas | `test_publicada_nunca_excluida_nem_editada`, `test_negativos` |

### Parte 2 — API REST e arquitetura

| Requisito | Teste |
|---|---|
| Endpoints públicos (monografias, cursos, orientadores) em JSON | `test_endpoints_publicos_json` |
| Endpoints restritos com CRUD autenticado | `test_anonimo_nao_acessa_restritos` |
| `POST /api/monografias`, `POST /api/bancas`, `GET /api/monografias?busca=…` | `criar_rascunho` e criação de bancas usam as URLs sem barra; `test_busca_restrita_por_filtros` |
| 6 microsserviços, cada um com API própria | `test_cada_servico_responde_pelo_gateway`, `test_cada_servico_tem_api_propria_documentada` (OpenAPI) |
| Redis: `busca:<hash>`, `upload_em_andamento:<id>`, rate limit | `test_cache_redis_hit_miss_e_chave_busca`, `test_upload_em_andamento_bloqueia_reenvio`, `test_limite_de_submissoes` |
| Eventos: submissão, agendamento, avaliação, publicação | `TestFilaDeEventos` |
| Fluxo exemplo (submete → fila → extrai/indexa → notifica orientador) | `test_fluxo_exemplo_notifica_orientador`, `test_fluxo_completo.py::test_fluxo_feliz_completo` |
| Escalabilidade | `test_replicas_balanceadas_pelo_gateway` (3 réplicas atendendo), `test_rajada_de_buscas_sem_erros` (500 buscas, 50 em paralelo, 0 erros) |
| Dashboard (curso, orientador, ano, taxa, tempo médio) | `test_relatorios_com_dados` |
| Histórico de alterações (quem, o quê, quando) | `test_edicao_em_rascunho_e_historico`, `test_historico_quem_o_que_quando` |
| Isolamento de falhas | `test_servico_fora_nao_derruba_o_resto_e_eventos_sao_processados_na_volta` |

## Problemas encontrados e corrigidos durante a verificação

| Problema | Correção |
|---|---|
| Limites de login (Nginx 10/min, DRF 20/min) impediam o seed de 31 logins | limites configuráveis por `.env` (`GATEWAY_RATE_LOGIN`, `THROTTLE_LOGIN`) |
| Seed usava o coordenador de SI para bancas de CC (403) | seed usa o coordenador de cada curso |
| `docker compose up --wait` falhava (workers sem healthcheck) | healthcheck simples nos workers |
| `/api/monografias/` ausente do Swagger (`get_queryset` quebrava sem usuário) | proteção `swagger_fake_view` + teste que falha se o schema gerar avisos |
| **Corrida no cache da busca:** invalidação antes do commit gravava resultado antigo na versão nova | invalidação em `transaction.on_commit` + teste |
| Coordenador criava aluno em outro curso e depois não o via (404) | coordenador gerencia apenas alunos do próprio curso (403 fora dele) |
| Nginx respeitava `max-age=60` do serviço em vez do TTL de borda de 30 s | `proxy_ignore_headers Cache-Control Expires` |
| `tcc_common` não declarava `django-cors-headers`; testes da lib sem `pythonpath` | dependência e `pythonpath` adicionados |

## O que continua fora desta verificação

* **Interface clicada no navegador:** as telas do frontend têm testes de componentes (Vitest) e são servidas e
  roteadas corretamente no E2E, mas o fluxo não foi executado clicando na interface (roteiro manual em `ROTEIRO_DEMO.md`).
* **Carga com 1 000–2 000 usuários no Docker:** o teste de carga medido foi o local (ver `TESTE_DE_CARGA.md`);
  no E2E há apenas a rajada de 500 buscas.
* **Auditoria de dependências** (`pip-audit`, `npm audit`).

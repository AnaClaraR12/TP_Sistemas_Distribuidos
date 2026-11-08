# Checklist final de aceite (seção 11 do roteiro)

Legenda: ✅ implementado e verificado por teste automatizado.

> **Atualização:** os itens antes marcados 🟡 (dependentes de Docker) foram verificados com o sistema real:
> o workflow `e2e.yml` sobe os 23 contêineres no GitHub Actions e roda 83 testes por requisito, todos passando.
> Mapeamento completo em [VERIFICACAO.md](VERIFICACAO.md).

## Requisitos tecnológicos

| Item | | Evidência |
|---|---|---|
| Django (última versão: 6.1.3) + DRF + Python 3.12 | ✅ | `services/*/requirements.txt` |
| PostgreSQL (database por serviço, usuário por serviço) | ✅ | `scripts/init-databases.sql`, `scripts/init-roles.sh`; testes rodam em PostgreSQL 16 |
| Redis: sessões, cache de busca, controle de uploads, rate limit | ✅ | `SESSION_ENGINE` (auth), `apps/indexacao/cache.py`, `upload_em_andamento:*`, `rl:submissao:*` — testes `test_upload.py`, `test_repositorio.py` |
| RabbitMQ com eventos assíncronos | ✅ | `tcc_common/events` (lógica testada com canal simulado); integração real: `tests/test_integracao_rabbitmq.py` (`make test-integracao`) |
| pdfplumber/pypdf para extração | ✅ | `apps/indexacao/extracao.py`, testes com PDFs reais |
| Frontend JavaScript consumindo a API | ✅ | `frontend/` (React), 10 testes Vitest, build de produção |
| Executa em Linux via Docker Compose | ✅ | `docker-compose.yml`, Dockerfiles, `Makefile` |

## Parte 1 — Autenticação, submissão e CRUD

| Item | | Evidência |
|---|---|---|
| django-allauth; login/senha; Argon2; política de senha | ✅ | `TestPoliticaSenha`, `test_hash_argon2`, `TestLogin` |
| Papéis admin, coordenador, professor/orientador, aluno, **membro externo por token** | ✅ | `Papel`, `MembroBanca.token_hash`, `test_token_externo_*` |
| Controle de acesso por permissões | ✅ | `tcc_common/auth/permissions.py`, grupos (data migration), `test_matriz_autorizacao.py` |
| Registro de auditoria | ✅ | `RegistroAuditoria`, `audit.registro`, `test_consumer_audit_registro_centraliza`, `test_login_registra_auditoria_e_ip` |
| Página principal + dashboard por tipo de usuário | ✅ | `Home`, `Dashboard` (widgets por papel), `GET /api/auth/me/dashboard-config/` |
| Modelos Aluno, Professor, Curso, Monografia, Banca, Avaliação, Documento Complementar | ✅ | `apps/academico/models.py`, `apps/monografias/models.py`, `apps/bancas/models.py` |
| Rascunho + orientador; upload PDF; acompanhamento de status | ✅ | `test_criar_sem_barra_final_e_dados_do_jwt`, `test_upload_ok_*`, `LinhaDoTempo` |
| Validação: só PDF, ≤ 50 MB, **SHA-256**, deduplicação | ✅ | `test_txt_renomeado_para_pdf_rejeitado`, `test_arquivo_maior_que_limite_413`, `test_duplicado_em_outra_monografia_409` |
| Banca **só após aprovação do orientador** | ✅ | `test_sem_aprovacao_do_orientador_409` |
| Extração de texto **assíncrona** | ✅ | `test_upload_nao_extrai_texto`, consumer `on_submetida`, submissão 20 MB em 0,004 s |
| Agendamento: data, local/link, membros (inclui externo por token) | ✅ | `test_criar_banca_inclui_orientador_e_gera_convites`, `test_banca_remota_com_link` |
| Validações: orientador aprovou; todos confirmaram; sem conflito de horário | ✅ | `test_agendar_sem_todas_confirmacoes_409`, `test_conflito_de_horario_409`, `test_agendamento_concorrente_sem_race_condition` |
| Notificação automática (fila) a membros e aluno | ✅ | `test_banca_agendada_notifica_todos_os_membros_e_aluno` |
| Avaliações (nota+parecer); **resultado só com todas**; atualiza status | ✅ | `test_resultado_nao_calculado_com_2_de_3`, `test_resultado_*`, `test_resultado_banca_consumer_idempotente` |
| Publicação automática (aprovada + correção + termo assinado) | ✅ | `test_publicacao_automatica_completa`, `test_fluxo_com_ressalvas_versao_corrigida`, `test_tentar_publicar_com_precondicao_faltando` (6 casos) |
| Busca pública por título, autor, orientador, curso, ano, palavras-chave | ✅ | `test_filtros` (10 casos), `test_busca_por_palavra_apenas_no_corpo_do_pdf` |
| Hash SHA-256 armazenado e **verificação de integridade** | ✅ | `test_integridade_violada`, `test_comando_verificar_integridade_todas` |
| Ações administrativas autenticadas; **admin só da rede institucional** | ✅ | `test_rede_institucional.py` (8 testes) |
| Leitura pública do repositório **sem autenticação** | ✅ | `test_publico_sem_autenticacao_e_token_invalido_ignorado` |
| CRUD de alunos, professores, cursos, monografias, bancas, avaliações | ✅ | `test_cadastros.py`, `test_fluxo.py`, `test_bancas.py` |
| Edição: monografias em rascunho, bancas não realizadas, avaliações pelo avaliador antes do fechamento | ✅ | `test_editar_fora_de_rascunho_409`, `test_nao_edita_banca_realizada`, `test_edicao_da_avaliacao_antes_e_depois_do_fechamento` |
| Exclusão só por autorizados e **nunca de publicadas** | ✅ | `test_excluir_publicada_409`, `test_matriz_exclusao_rascunho` |

## Parte 2 — API REST e arquitetura

| Item | | Evidência |
|---|---|---|
| Endpoints públicos: monografias publicadas (busca+filtros), cursos, orientadores (JSON) | ✅ | `test_endpoints_publicos_cursos_e_orientadores` |
| Endpoints restritos (CRUD autenticado): alunos, monografias, bancas, avaliações | ✅ | `test_anonimo_nao_acessa_restritos` |
| Exemplos do enunciado (`POST /api/monografias`, `POST /api/bancas`, `GET /api/monografias?busca=...`) | ✅ | router com barra opcional; `test_criar_sem_barra_final_*`, `criar_banca` usa `/api/bancas`, `test_listagem_por_papel_e_busca` |
| 6 microsserviços independentes, cada um com API própria | ✅ | `services/*` + Swagger por serviço |
| Redis com chaves `busca:<hash>` e `upload_em_andamento:<monografia_id>` | ✅ | `test_cache_hit_miss_e_normalizacao`, `test_submeter_202_evento_e_lock` |
| Eventos: submissão, agendamento, avaliação registrada, publicação | ✅ | `docs/EVENTOS.md`, testes de outbox em cada serviço |
| Fluxo exemplo: submete → evento → extrai/indexa → notifica orientador | ✅ | etapas testadas isoladamente; ponta a ponta em `tests/e2e/test_fluxo_completo.py` |
| Escalabilidade (cache, filas, serviços independentes, APIs desacopladas) com **teste de carga** | ✅ | `docs/TESTE_DE_CARGA.md` (números reais, execução local) |
| Dashboard Chart.js: curso, orientador, ano, taxa de aprovação, tempo médio | ✅ | `frontend/src/charts/Graficos.jsx`, `test_relatorios.py` |
| Frontend: submissão, aprovação, agendamento, avaliação, pesquisa pública | ✅ | `frontend/src/pages/*` |
| **Histórico de alterações**: quem, o quê, quando | ✅ | `Historico()` + `/historico/`; `test_editar_rascunho_e_historico`, `test_historico_registra_quem_alterou`, `test_historico_da_avaliacao` |

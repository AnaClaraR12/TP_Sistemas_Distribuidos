# Catálogo de eventos (exchange `tcc.events`, tipo *topic*)

Fonte da verdade dos campos obrigatórios: `libs/tcc_common/tcc_common/events/schemas.py`
(validado na publicação). Filas: `<serviço>.<routing_key>` (com `#`→`todos`, `*`→`qualquer`),
retries `<fila>.retry.1..3` (TTL 10 s, 60 s, 5 min) e `<fila>.dlq` via `tcc.dlx`.

## Envelope

```json
{
  "event_id": "c1f0…",            "type": "monografia.submetida",
  "schema_version": 1,             "occurred_at": "2026-05-10T14:03:11Z",
  "producer": "monografias-service", "correlation_id": "<X-Request-ID>",
  "actor_id": "<uuid do usuário ou null>", "data": { }
}
```

`message_id = event_id`, `delivery_mode = 2` (persistente), *publisher confirms*.

## Eventos

`MONO_BASE` = `id, titulo, status, aprovacao_orientador, aluno_id, orientador_id, curso_id`.

| Routing key | Produtor | Consumidores | `data` obrigatório |
|---|---|---|---|
| `cadastro.curso.upserted` / `.deleted` | auth | monografias, repositório, notificações, relatórios | id, nome, codigo, coordenador_id |
| `cadastro.professor.upserted` / `.deleted` | auth | todos | id, nome, email, departamento |
| `cadastro.aluno.upserted` / `.deleted` | auth | monografias, notificações | id, nome, email, matricula, curso_id, orientador_id |
| `monografia.submetida` | monografias | **repositório** (extrai/indexa), notificações (orientador), relatórios, bancas (read model) | MONO_BASE + sha256, submetida_em |
| `monografia.texto_extraido` | repositório | monografias (libera lock), notificações | id, paginas, sem_texto |
| `monografia.extracao_falhou` | repositório | monografias (libera lock), notificações | id, motivo |
| `monografia.aprovada_orientador` | monografias | bancas (read model), notificações, relatórios | MONO_BASE + sha256_aprovado |
| `monografia.rejeitada_orientador` | monografias | notificações, bancas, relatórios | MONO_BASE + motivo |
| `monografia.resultado_registrado` | monografias | bancas, relatórios | MONO_BASE + resultado, exige_correcao |
| `monografia.integridade_violada` | monografias | notificações (admin+coord), auth (auditoria crítica) | MONO_BASE + sha_esperado, sha_atual |
| `monografia.publicada` | monografias | **repositório** (público + cache), **notificações** (aluno), relatórios, bancas | MONO_BASE + resumo, palavras_chave, autor_nome, orientador_nome, curso_nome, ano_defesa, sha256, publicada_em |
| `monografia.excluida` | monografias | bancas, repositório, relatórios | id |
| `documento.enviado` | monografias | (registro interno; `tentar_publicar` é chamado na própria transação) | monografia_id, tipo |
| `banca.convite_enviado` | bancas | notificações | banca_id, monografia_id, membro{nome,email,tipo}, expira_em (+ `token` só p/ externo; mascarado no outbox após publicar) |
| `banca.agendada` | bancas | **notificações (todos os membros + aluno)** | banca_id, monografia_id, aluno_id, data_hora, local, link, membros[] |
| `banca.cancelada` | bancas | notificações | banca_id, monografia_id, aluno_id, motivo, membros[] |
| `avaliacao.registrada` | bancas | **bancas** (verifica fechamento e calcula) | banca_id, avaliacao_id, membro_id |
| `banca.resultado_calculado` | bancas | **monografias**, notificações, relatórios | banca_id, monografia_id, aluno_id, orientador_id, resultado, media, exige_correcao, data_defesa |
| `repositorio.indexado` | repositório | (observabilidade) | monografia_id |
| `audit.registro` | todos (exceto auth, que grava direto) | auth | usuario_id, acao, recurso, recurso_id, detalhes (+ ip, user_agent, papel, nivel) |

## Garantias

* **Durabilidade:** exchange/filas duráveis + mensagens persistentes + outbox no banco do produtor.
* **Idempotência:** `evento_processado(event_id único)`; corrida entre workers tratada por `IntegrityError`.
* **Ack após commit**; falha → retry com backoff; esgotou → `falha_definitiva()` (ex.: `extracao_falhou`) e DLQ.
* **Ordem:** não garantida entre filas; handlers são tolerantes (ex.: read model ignora evento sem `status`).

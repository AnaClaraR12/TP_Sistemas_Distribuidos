# Roteiro de demonstração (≈ 10 min)

Pré-requisito: `make up && make seed` (usuários e senha `Demo@Tcc#2026` — ver README).
Abra em abas: <http://localhost:8080> (sistema), <http://localhost:15672> (RabbitMQ, `tcc`/`tcc-dev-123`),
<http://localhost:8025> (MailHog).

| Tempo | O que mostrar | Como |
|---|---|---|
| 0:00–1:30 | **Arquitetura** | `docs/ARQUITETURA.md` (diagrama de contêineres): 6 serviços, gateway, DB por serviço, outbox → RabbitMQ, Redis. `docker compose ps` |
| 1:30–2:30 | **Repositório público sem login** | Página inicial → pesquisar "sistemas distribuídos" → filtros (curso/orientador/ano) → detalhe → baixar PDF |
| 2:30–4:30 | **Fluxo do aluno** | Entrar como `aluno20@demo.tcc.br` → Nova monografia → enviar PDF (mostrar barra de progresso; tentar um `.txt` renomeado → erro de formato) → Submeter (resposta imediata, 202) |
| 4:30–5:15 | **Fila no RabbitMQ** | Painel → *Queues*: `repositorio.monografia.submetida` (mensagem consumida), filas `.retry.N` e `.dlq`. MailHog: e-mail "Nova submissão" ao orientador |
| 5:15–6:15 | **Orientador** | Entrar como o orientador → Dashboard (pendências) → aprovar. Mostrar hash SHA-256 e "Verificar integridade" |
| 6:15–7:30 | **Banca** | Coordenador (`prof1@…`) → Agendar banca com 1 interno + 1 externo → tentar "Agendar" (409: confirmações pendentes) → MailHog: link `/banca/externo/<token>` → abrir em aba anônima e confirmar → membros internos confirmam → Agendar → e-mails a todos + aluno |
| 7:30–8:30 | **Avaliação e publicação** | Marcar realizada → 3 avaliações (uma pelo link externo) → resultado calculado → aluno envia termo → coordenador valida → status **publicada** → aparece na busca pública |
| 8:30–9:15 | **Cache HIT/MISS** | `curl -si "localhost:8080/api/repositorio/monografias/?busca=redis" \| grep -i cache` duas vezes (MISS → HIT; `X-Proxy-Cache` do Nginx) |
| 9:15–9:40 | **Carga** | `docs/TESTE_DE_CARGA.md`: tabela sem cache × com cache × 3 réplicas |
| 9:40–10:00 | **Falha de serviço** | `docker compose stop notificacoes-worker repositorio-worker` → busca pública continua respondendo; submeter algo → mensagens acumulam na fila → `docker compose start …` → fila esvazia, e-mails chegam |

Extras se houver tempo: dashboard com gráficos (coordenador), histórico de alterações (quem/o quê/quando),
auditoria, `/admin/` com `INSTITUTIONAL_CIDRS` sem o IP do host → 403.

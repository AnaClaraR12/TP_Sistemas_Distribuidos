# API — índice e exemplos

Toda a API é acessada pelo gateway: **`http://localhost:8080`**. Swagger de cada serviço (botão
*Authorize* aceita `Bearer <access>`):

| Serviço | Swagger | Schema |
|---|---|---|
| auth | <http://localhost:8080/api/auth/docs/> | `/api/auth/schema/` |
| monografias | <http://localhost:8080/api/monografias/docs/> | `/api/monografias/schema/` |
| bancas | <http://localhost:8080/api/bancas/docs/> | `/api/bancas/schema/` |
| repositório | <http://localhost:8080/api/repositorio/docs/> | `/api/repositorio/schema/` |
| notificações | <http://localhost:8080/api/notificacoes/docs/> | `/api/notificacoes/schema/` |
| relatórios | <http://localhost:8080/api/relatorios/docs/> | `/api/relatorios/schema/` |

Erros sempre no formato `{"codigo": "...", "mensagem": "...", "detalhes": {...}}`. Paginação
`?limit=` (padrão 20, máx. 50) e `?offset=`. Datas ISO-8601. Rotas aceitam com e sem barra final.

## Públicos (sem token)

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/repositorio/monografias/?busca=&titulo=&autor=&orientador=&curso=&ano_defesa=&palavras_chave=&ordenar=` | busca pública (só publicadas), `X-Cache: HIT/MISS` |
| GET | `/api/repositorio/monografias/{id}/` · `/{id}/download/` | detalhe e PDF (hash verificado, contador de downloads) |
| GET | `/api/repositorio/cursos/` · `/api/repositorio/orientadores/` | listas públicas |
| POST | `/api/auth/token/` · `/api/auth/token/refresh/` | login (JWT) e renovação |
| GET | `/.well-known/jwks.json` | chave pública |
| GET/POST | `/api/bancas/externo/minha-banca/` · `/confirmar/` · `/avaliacao/` | membro externo (header `X-Banca-Token`) |
| GET | `/health/`, `/ready/` (e `/api/<svc>/health/`) | healthchecks |

## Restritos (Bearer)

* **auth** — `GET /api/auth/me/` · `GET /api/auth/me/dashboard-config/` · `POST /api/auth/logout/` · CRUD
  `/api/auth/cursos/`, `/professores/`, `/alunos/` (+ `/{id}/historico/`) · `GET /api/auth/auditoria/` ·
  `/api/auth/admin/usuarios/` (admin + rede institucional) · Django Admin `/admin/` (rede institucional).
* **monografias** — CRUD `/api/monografias` (+`?busca=`) · `POST /{id}/arquivo/` · `POST /{id}/submeter/` ·
  `POST /{id}/aprovar-orientador/` · `POST /{id}/rejeitar-orientador/` · `POST /{id}/verificar-integridade/` ·
  `POST /{id}/validar-correcao/` · `GET/POST /{id}/documentos/` · `POST /{id}/documentos/{doc}/validar-assinatura/` ·
  `GET /{id}/historico/` · `GET /{id}/arquivo/download/`.
* **bancas** — CRUD `/api/bancas` · `POST /{id}/agendar/` · `POST /{id}/cancelar/` · `POST /{id}/marcar-realizada/` ·
  `POST/DELETE /{id}/membros/[{m}/]` · `POST /{id}/membros/{m}/confirmar/` · `GET/POST /{id}/avaliacoes/` ·
  `PATCH /api/bancas/{id}/avaliacoes/{a}/` e `/api/avaliacoes/{a}/` · `GET /{id}/pdf/` · `GET /{id}/historico/`.
* **notificações** — `GET /api/notificacoes/minhas/` · `POST /api/notificacoes/{id}/lida/`.
* **relatórios** — `GET /api/relatorios/{monografias-por-curso|monografias-por-orientador|monografias-por-ano-defesa|taxa-aprovacao|tempo-medio-submissao-defesa|resumo}/`.
* **interno (serviço-a-serviço, `X-Service-Token`, não exposto no gateway)** — `GET /internal/monografias/{id}/` e `/arquivo/`.

## Exemplos `curl` (os do enunciado incluídos)

```bash
GW=http://localhost:8080
TOKEN=$(curl -s -X POST $GW/api/auth/token/ -H 'Content-Type: application/json' \
  -d '{"email":"aluno1@demo.tcc.br","password":"Demo@Tcc#2026"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access"])')

# POST /api/monografias  (rascunho)
curl -s -X POST $GW/api/monografias -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"titulo":"Sistemas distribuídos na prática","resumo":"...","palavras_chave":["a","b","c"],"orientador_id":"<uuid>"}'

# upload + submissão
curl -s -X POST $GW/api/monografias/<id>/arquivo/ -H "Authorization: Bearer $TOKEN" -F arquivo=@tcc.pdf
curl -s -X POST $GW/api/monografias/<id>/submeter/ -H "Authorization: Bearer $TOKEN"

# GET /api/monografias?busca=sistemas+distribuidos
curl -s "$GW/api/monografias?busca=sistemas+distribuidos" -H "Authorization: Bearer $TOKEN"

# POST /api/bancas  (coordenador ou orientador)
curl -s -X POST $GW/api/bancas -H "Authorization: Bearer $TOKEN_COORD" -H 'Content-Type: application/json' -d '{
  "monografia_id":"<id>","data_hora_inicio":"2026-12-01T14:00:00-03:00","local":"Sala 101",
  "membros":[{"tipo":"interno","professor_id":"<uuid>"},{"tipo":"externo","nome":"Dra. X","email":"x@ufmg.br","instituicao":"UFMG"}]}'

# busca pública (sem login) — repita para ver X-Cache: HIT
curl -si "$GW/api/repositorio/monografias/?busca=redis" | grep -i -E 'x-cache|x-proxy-cache'

# membro externo
curl -s $GW/api/bancas/externo/minha-banca/ -H "X-Banca-Token: <token do e-mail>"
```

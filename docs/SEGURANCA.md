# Checklist de segurança

| Item | Status | Evidência |
|---|---|---|
| Senhas com **Argon2** + política forte (≥ 12, maiúscula, minúscula, dígito, símbolo, não comum, não numérica, não similar ao e-mail) | ✅ | `services/auth/config/settings/base.py`, `apps/contas/validators.py`, `tests/test_autenticacao.py::TestPoliticaSenha` |
| Bloqueio por tentativas (5 em 15 min, Redis) | ✅ | `apps/contas/backends.py`, `test_bloqueio_apos_5_falhas` |
| JWT RS256, access 15 min, refresh 7 dias com rotação, logout com blacklist de `jti` | ✅ | `apps/contas/tokens.py`, `TestJWT` |
| JWT validado **localmente** (sem chamar o auth); refresh não serve como access; chave errada/adulterado → 401 | ✅ | `tcc_common/auth/jwt.py`, `test_token_adulterado`, `test_validacao_por_jwks_sem_chave_local` |
| Área administrativa só da rede institucional; `X-Real-IP`/`X-Forwarded-For` só aceitos do gateway | ✅ | `tcc_common/middleware/rede_institucional.py`, `test_rede_institucional.py` |
| Permissões explícitas em toda view; matriz papel × endpoint testada | ✅ | `DEFAULT_PERMISSION_CLASSES = IsAutenticado`, `services/monografias/tests/test_matriz_autorizacao.py` (64 casos) |
| **IDOR**: aluno não acessa monografia de outro (403) | ✅ | `test_idor_aluno_nao_ve_monografia_de_outro` |
| Nenhum endpoint restrito responde 200 a anônimo | ✅ | `test_anonimo_nao_acessa_restritos`, `test_nenhum_endpoint_restrito_responde_200_a_anonimo` |
| Upload: extensão + magic bytes `%PDF-` + Content-Type; tamanho em streaming; SHA-256; dedup | ✅ | `apps/monografias/arquivos.py`, `tests/test_upload.py` |
| *Path traversal*: nome do arquivo definido pelo servidor (`monografias/<uuid>/<sha256>.pdf`) | ✅ | `test_nome_do_usuario_nao_define_caminho` |
| Token de membro externo: `secrets.token_urlsafe(32)`, só o SHA-256 no banco, expiração, revogação, escopo restrito, rate limit por IP | ✅ | `apps/bancas/servicos.py`, `test_token_externo_*` |
| Token externo nunca persistido em claro (outbox mascarado, e-mail armazenado mascarado) | ✅ | `publish_outbox.mascarar_sensiveis`, `test_token_mascarado_no_outbox_apos_publicacao`, `test_convite_externo_tem_link_com_token_mas_banco_nao` |
| Rate limiting: submissões/hora (Redis), login (DRF + Nginx), público 60/min/IP (DRF) + `limit_req` (Nginx) | ✅ | `test_rate_limit_429_com_retry_after`, `test_throttling_anonimo` |
| Mass assignment: serializers com campos explícitos; `status` somente leitura e protegido no `save()` | ✅ | `test_criar_sem_barra_final_e_dados_do_jwt`, `test_status_nao_muda_por_atribuicao_direta` |
| SQL injection: apenas ORM / parâmetros (`cur.execute(sql, [params])`) | ✅ | revisão de código |
| XSS: trecho destacado renderizado sem `innerHTML`; CSP no gateway | ✅ | `Destaque` (+ teste Vitest), `gateway/templates/default.conf.template` |
| Cabeçalhos: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, CSP | ✅ | gateway + `SECURE_CONTENT_TYPE_NOSNIFF` |
| CORS restrito (`CORS_ALLOWED_ORIGINS`, vazio por padrão — o frontend é mesma origem) | ✅ | `settings_base.py` |
| Cookies `Secure`/`HttpOnly` em produção (`COOKIES_SEGUROS`) | ✅ | `settings_base.py` |
| `DEBUG=False` por padrão; `SECRET_KEY` obrigatória sem DEBUG | ✅ | `settings_base.construir` |
| Nenhum segredo no repositório (`.env`, `secrets/*.pem` no `.gitignore`; chaves via Docker secrets) | ✅ | `.gitignore`, `docker-compose.yml`, hook `detect-private-key` |
| Nenhum segredo em log (formatter mascara `token`, `password`, `authorization`…) | ✅ | `tcc_common/api/logging.py`, `test_log_json_mascara_campos_sensiveis` |
| Integridade: SHA-256 aprovado + verificação sob demanda e diária, alerta crítico | ✅ | `servicos.verificar_integridade`, `test_integridade_violada` |
| Serviço não acessa banco de outro (usuário Postgres por serviço) | ✅ | `scripts/init-roles.sh` |
| Dependências sem CVE (`pip-audit`, `npm audit`) | ⚠️ executar | `pip install pip-audit && pip-audit -r services/<svc>/requirements.txt`; `cd frontend && npm audit` |

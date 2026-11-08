#!/bin/sh
# Um usuário Postgres por serviço, com acesso SOMENTE ao próprio database.
# Garante na infraestrutura a regra "um serviço nunca acessa o banco de outro".
set -e

criar() {
  servico="$1"; senha="$2"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE ${servico}_user LOGIN PASSWORD '${senha}';
REVOKE ALL ON DATABASE ${servico}_db FROM PUBLIC;
GRANT ALL PRIVILEGES ON DATABASE ${servico}_db TO ${servico}_user;
ALTER DATABASE ${servico}_db OWNER TO ${servico}_user;
SQL
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "${servico}_db" \
    -c "ALTER SCHEMA public OWNER TO ${servico}_user;"
}

criar auth "$DB_PASSWORD_AUTH"
criar monografias "$DB_PASSWORD_MONOGRAFIAS"
criar bancas "$DB_PASSWORD_BANCAS"
criar repositorio "$DB_PASSWORD_REPOSITORIO"
criar notificacoes "$DB_PASSWORD_NOTIFICACOES"
criar relatorios "$DB_PASSWORD_RELATORIOS"

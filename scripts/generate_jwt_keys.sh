#!/bin/sh
# Gera o par de chaves RSA (RS256) usado pelo auth-service para assinar JWT.
# Saída: secrets/jwt_private.pem (somente auth-service) e secrets/jwt_public.pem (todos).
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)/secrets"
mkdir -p "$DIR"
if [ -f "$DIR/jwt_private.pem" ] && [ "$1" != "--forcar" ]; then
  echo "Chaves já existem em $DIR (use --forcar para regerar)."
  exit 0
fi
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$DIR/jwt_private.pem"
openssl rsa -in "$DIR/jwt_private.pem" -pubout -out "$DIR/jwt_public.pem"
chmod 644 "$DIR/jwt_private.pem" "$DIR/jwt_public.pem"  # lidas pelo usuário 'app' do container (secret só-leitura)
echo "Chaves geradas em $DIR"

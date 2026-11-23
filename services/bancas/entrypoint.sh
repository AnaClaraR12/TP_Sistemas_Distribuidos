#!/bin/sh
# Inicialização do container: migrações, estáticos e topologia de filas.
set -e
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
fi
python manage.py collectstatic --noinput >/dev/null 2>&1 || true
python manage.py declarar_topologia || echo "aviso: RabbitMQ indisponível para declarar topologia"
exec "$@"

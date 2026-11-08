"""Extensões unaccent/pg_trgm (quando disponíveis) e índice trigram em titulo_norm.

No Docker (imagem postgres:16) as extensões existem e são criadas também pelo
scripts/init-databases.sql. Em ambientes sem contrib a migração apenas registra aviso.
"""

from django.db import migrations

SQL = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'unaccent') THEN
    CREATE EXTENSION IF NOT EXISTS unaccent;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_trgm') THEN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE INDEX IF NOT EXISTS doc_titulo_trgm ON indexacao_documentoindexado USING gin (titulo_norm gin_trgm_ops);
  ELSE
    RAISE NOTICE 'pg_trgm indisponível: índice trigram não criado';
  END IF;
END $$;
"""

REVERSO = "DROP INDEX IF EXISTS doc_titulo_trgm;"


class Migration(migrations.Migration):
    dependencies = [("indexacao", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSO)]

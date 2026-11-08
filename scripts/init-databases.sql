-- Cria um database por serviço (database-per-service) + extensões de busca.
-- Executado automaticamente pelo container postgres (docker-entrypoint-initdb.d).
CREATE DATABASE auth_db;
CREATE DATABASE monografias_db;
CREATE DATABASE bancas_db;
CREATE DATABASE repositorio_db;
CREATE DATABASE notificacoes_db;
CREATE DATABASE relatorios_db;

\connect repositorio_db
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

\connect monografias_db
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

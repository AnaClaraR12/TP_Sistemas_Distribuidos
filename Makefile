# Atalhos do projeto (Linux com Docker).
SERVICOS := auth monografias bancas repositorio notificacoes relatorios
DC := docker compose
PYTHON ?= python3

.PHONY: help keys env up down logs ps migrate test test-local test-integracao lint fmt seed e2e loadtest scale build clean

help:  ## lista os comandos
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

env:  ## cria o .env a partir do .env.example (se não existir)
	@test -f .env || cp .env.example .env

keys:  ## gera o par de chaves RSA do JWT em secrets/
	sh scripts/generate_jwt_keys.sh

build: env keys  ## constrói as imagens
	$(DC) build

up: env keys  ## sobe todo o sistema (gateway em http://localhost:8080)
	$(DC) up -d --build
	@echo "Gateway: http://localhost:8080  | RabbitMQ: http://localhost:15672 | MailHog: http://localhost:8025"

down:  ## derruba os containers (mantém volumes)
	$(DC) down

clean:  ## derruba tudo e APAGA os volumes
	$(DC) down -v

logs:  ## acompanha os logs
	$(DC) logs -f --tail=100

ps:
	$(DC) ps

migrate:  ## aplica migrações em todos os serviços
	@for s in $(SERVICOS); do $(DC) exec -T $$s-service python manage.py migrate --noinput || exit 1; done

-include .env

test:  ## roda pytest de cada serviço dentro do seu container (requer `make up`)
	@for s in $(SERVICOS); do \
	  echo "=== $$s ==="; \
	  $(DC) run --rm --no-deps --entrypoint sh -e DJANGO_SETTINGS_MODULE=config.settings.test \
	    -e DATABASE_URL=postgres://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@postgres:5432/$${s}_db \
	    $$s-service -c "pip install --user -q -r requirements-dev.txt && python -m pytest --cov=apps --cov-report=term-missing" || exit 1; \
	done

test-local:  ## roda TODOS os testes sem Docker (Postgres embutido via pgserver)
	$(PYTHON) scripts/run_tests_local.py

test-integracao:  ## testes contra RabbitMQ real (precisa do compose de pé)
	$(DC) run --rm --no-deps --entrypoint sh -w /libs/tcc_common -e RABBITMQ_URL_TESTE=$(RABBITMQ_URL) \
	  -e DJANGO_SETTINGS_MODULE=tests.settings_teste \
	  -e DATABASE_URL=postgres://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@postgres:5432/postgres auth-service \
	  -c "pip install --user -q pytest pytest-django fakeredis && python -m pytest tests -p no:cacheprovider"

lint:  ## ruff + black --check
	ruff check libs services scripts loadtest tests
	black --check libs services scripts loadtest tests

fmt:  ## formata o código
	ruff check --fix libs services scripts loadtest tests
	black libs services scripts loadtest tests

seed:  ## popula dados de demonstração via API do gateway
	$(PYTHON) scripts/seed_demo.py --gateway http://localhost:8080

e2e:  ## teste ponta a ponta contra o gateway (sistema de pé + seed)
	$(PYTHON) -m pytest tests/e2e -v

loadtest:  ## teste de carga (pico de defesa) — ver loadtest/README.md
	$(PYTHON) -m locust -f loadtest/locustfile.py --host http://localhost:8080 --headless -u 1000 -r 50 -t 5m --csv loadtest/resultados/pico

scale:  ## 3 réplicas do repositório e dos workers (sem o override, que fixa portas por serviço)
	$(DC) -f docker-compose.yml up -d --scale repositorio-service=3 --scale repositorio-worker=3 --scale monografias-service=2

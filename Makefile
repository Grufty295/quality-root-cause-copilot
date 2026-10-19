COMPOSE ?= docker compose -f docker-compose.yml -f docker-compose.langfuse.yml
PROJECT := arnes-8d
SEED    ?= 42

LANGFUSE_VOLUMES := langfuse_postgres_data langfuse_clickhouse_data langfuse_clickhouse_logs langfuse_minio_data langfuse_redis_data
LANGFUSE_SERVICES := langfuse-web langfuse-worker langfuse-clickhouse langfuse-minio langfuse-redis langfuse-postgres

.DEFAULT_GOAL := help
.PHONY: help init init-langfuse up up-d dev local observability down reset-db reset-observability logs ps psql migrate test seed eval-retrieval eval-agent eval-baseline eval-semantic eval-gates build-evals llm-diagnose audit

help: ## Lista los comandos
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

init: ## Crea .env desde .env.example y la carpeta traces/ (idempotente)
	@test -f .env || { cp .env.example .env && echo ".env creado: revisa POSTGRES_PASSWORD"; }
	@mkdir -p traces

init-langfuse: init ## Crea .env.langfuse con secretos aleatorios (idempotente)
	@command -v openssl >/dev/null || { echo "Falta openssl para generar secretos"; exit 1; }
	@test -f .env.langfuse || { \
	  cp .env.langfuse.example .env.langfuse; \
	  for p in NEXTAUTH SALT CLICKHOUSE REDIS MINIO PG ADMIN; do \
	    sed -i.bak "s|CHANGEME_$$p|$$(openssl rand -hex 16)|g" .env.langfuse; \
	  done; \
	  sed -i.bak "s|CHANGEME_ENCRYPTION|$$(openssl rand -hex 32)|g" .env.langfuse; \
	  rm -f .env.langfuse.bak; \
	  echo ".env.langfuse creado con secretos aleatorios"; }
	@grep -q '^LANGFUSE_SECRET_KEY=sk-lf-local-dev$$' .env && { \
	  sed -i.bak "s|^LANGFUSE_PUBLIC_KEY=.*|LANGFUSE_PUBLIC_KEY=pk-lf-$$(openssl rand -hex 16)|; s|^LANGFUSE_SECRET_KEY=.*|LANGFUSE_SECRET_KEY=sk-lf-$$(openssl rand -hex 16)|" .env; \
	  rm -f .env.bak; \
	  echo "Llaves del proyecto de Langfuse generadas en .env"; } || true

up: init ## Levanta db, api y web en primer plano
	$(COMPOSE) up --build

up-d: init ## Levanta db, api y web en segundo plano
	$(COMPOSE) up --build -d

dev: init ## db + api con recarga; el web va en el host (npm run dev)
	$(COMPOSE) -f docker-compose.dev.yml up --build -V db api

local: init ## Todo mas Ollama (perfil local; usa LOCAL_PROVIDER=ollama)
	$(COMPOSE) --profile local up --build

observability: init-langfuse ## Todo mas Langfuse en segundo plano (UI en http://localhost:3001)
	UV_EXTRA_GROUPS="--group observabilidad" $(COMPOSE) --profile observability up --build -d
	@echo "Langfuse: http://localhost:3001  (usuario admin@example.com; clave: LANGFUSE_INIT_USER_PASSWORD en .env.langfuse)"
	@echo "Para exportar trazas: TRACE_EXPORTER=langfuse en .env y luego: $(COMPOSE) up -d api  (restart no relee .env)"

down: ## Detiene todos los servicios, incluidos los de perfiles (conserva los datos)
	$(COMPOSE) --profile '*' down

reset-db: ## Borra SOLO la base de datos (pgdata); no toca modelos descargados
	@read -p "Esto borra los datos de Postgres. Continuar? [y/N] " a; [ "$$a" = "y" ] || exit 1
	$(COMPOSE) --profile '*' down
	docker volume rm $(PROJECT)_pgdata

reset-observability: ## Borra los datos de Langfuse (trazas, usuarios, proyecto)
	@read -p "Esto borra todos los datos de Langfuse. Continuar? [y/N] " a; [ "$$a" = "y" ] || exit 1
	$(COMPOSE) --profile observability rm -sf $(LANGFUSE_SERVICES)
	docker volume rm $(foreach v,$(LANGFUSE_VOLUMES),$(PROJECT)_$(v))

logs: ## Sigue los logs de la API
	$(COMPOSE) logs -f --tail=100 api

ps: ## Estado de los servicios
	$(COMPOSE) --profile '*' ps

psql: ## Consola psql dentro del contenedor de la base
	$(COMPOSE) exec db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

migrate: ## Aplica migraciones pendientes (la API tambien migra al arrancar)
	$(COMPOSE) exec api alembic upgrade head

test: ## Corre pytest contra una base aparte (eightd_test), nunca la de la demo
	$(COMPOSE) exec db sh -c 'dropdb -U "$$POSTGRES_USER" --if-exists eightd_test && createdb -U "$$POSTGRES_USER" eightd_test'
	$(COMPOSE) exec api sh -c 'export DATABASE_URL="$${DATABASE_URL%/*}/eightd_test" && alembic upgrade head && pytest -q'

seed: ## Carga catalogos, usuarios de demo y corpus (los CSV se generan con data/generator/generate.py)
	$(COMPOSE) exec api python -m app.seed

eval-retrieval: ## Recuperación: Recall/MRR/nDCG por búsqueda y modo (dev). Con TEST=1 incluye la partición sellada
	$(COMPOSE) exec api python -m app.evalkit.retrieval $(if $(TEST),--test)

eval-agent: ## Agente vs esperado (dev, 3 repeticiones). GASTA tokens. ARGS="--name dev-v6 --variants con_enlaces --repeats 3 --concurrency 3" o "--casos EV-01,EV-05,EV-09 --repeats 1" para un humo
	$(COMPOSE) exec api python -m app.evalkit.agent $(ARGS)

eval-baseline: ## Línea base trivial (NCR más parecida con 8D) por partición; no llama al modelo
	$(COMPOSE) exec api python -m app.evalkit.baseline

eval-semantic: ## Juez LLM (DeepEval + Ragas) sobre las corridas del agente. GASTA tokens. ARGS="--max-runs 6 --metrics citas" (o "--export-labels 40" para la muestra a etiquetar a mano)
	$(COMPOSE) exec api python -m app.evalkit.semantic $(ARGS)

eval-gates: ## Gates bloqueantes sobre los reportes ya generados (no llama al modelo). VARIANT=con_enlaces SPLIT=all
	$(COMPOSE) exec api python -m app.evalkit.gates --variant $(or $(VARIANT),con_enlaces) --split $(or $(SPLIT),dev)

build-evals: ## Reconstruye y actualiza la API con DeepEval, Ragas y Langfuse y el commit actual
	GIT_SHA=$$(git rev-parse --short HEAD 2>/dev/null) UV_EXTRA_GROUPS="--group evals --group observabilidad" $(COMPOSE) up --build -d api

llm-diagnose: ## Por qué falla la llamada al modelo: config efectiva, key, proveedores y matriz de parámetros. DEST=api para el otro destino; CASO=EV-01 corre el agente real y repite el request que falla
	$(COMPOSE) exec api python -m app.evalkit.diagnose $(if $(CASO),--caso $(CASO),--dest $(or $(DEST),local))

audit: ## Verifica la cadena de hashes del log de auditoria e imprime el hash de la cabeza
	$(COMPOSE) exec db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "SELECT * FROM audit_verify()"'
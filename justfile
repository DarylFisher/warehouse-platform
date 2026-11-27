set dotenv-load := true

# Cloud sessions add docker-compose.cloud.yml (proxy CA for builds, sandbox ulimits).
compose := if env_var_or_default("CLAUDE_CODE_REMOTE", "") == "true" {
    "docker compose -f docker-compose.yml -f docker-compose.cloud.yml"
} else {
    "docker compose"
}

# List commands
default:
    @just --list

# Start the full local stack (databases, Keycloak, migrations, API)
up:
    {{compose}} up -d --build
    @echo "API: http://localhost:8100/docs"

# Start only the backing services, for running the API on the host
deps:
    {{compose}} up -d postgres clickhouse keycloak

# Run the API on the host with hot reload (start backing services with `just deps`)
run:
    cd backend && uv run alembic upgrade head && uv run uvicorn wap.api.main:app --reload --port 8100

# Print a dev access token for a Keycloak user (north.admin, south.admin, ops.both)
token user="north.admin":
    @cd backend && uv run --quiet python -m wap.cli.dev_token {{user}}

# Stop the stack (data volumes are kept)
down:
    {{compose}} down

# Stop the stack and delete all local data
reset-db:
    {{compose}} down -v
    {{compose}} up -d --build

# Apply kernel migrations
migrate:
    {{compose}} run --rm migrate

# Add database roles introduced since the Postgres volume was created (safe to re-run)
db-roles:
    {{compose}} exec -T postgres bash /docker-entrypoint-initdb.d/01-roles-and-databases.sh

# Run the outbox relay on the host (ships events to ClickHouse)
relay:
    cd backend && uv run python -m wap.cli.relay

# Create two demo tenants with sample data
seed:
    {{compose}} run --rm migrate python -m wap.cli.seed

# Follow API logs
logs:
    {{compose}} logs -f api

# Lint and type check
lint:
    cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright

# Format code
fmt:
    cd backend && uv run ruff format . && uv run ruff check --fix .

# Lint, type check and run all tests (needs `just deps` or `just up`)
test: lint
    cd backend && uv run pytest

# Run only the tests that need no database
test-unit:
    cd backend && uv run pytest -m "not integration"

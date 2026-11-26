set dotenv-load := true

compose := "docker compose"

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

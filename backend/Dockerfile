# syntax=docker/dockerfile:1
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

# UV_SYSTEM_CERTS makes uv use the system trust store, so an extra CA added
# below (for a TLS-intercepting proxy, as in Claude Code cloud sessions) works.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_SYSTEM_CERTS=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Optional extra CA certificate, passed as the build secret "extra_ca"
# (see docker-compose.cloud.yml). Without the secret this step does nothing.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then \
      cp /run/secrets/extra_ca /usr/local/share/ca-certificates/extra-ca.crt \
      && update-ca-certificates; \
    fi

WORKDIR /app

# Dependencies first, for layer caching.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# The project is installed editable, so docker-compose can mount ./src for reload.
COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8100
CMD ["uvicorn", "wap.api.main:app", "--host", "0.0.0.0", "--port", "8100"]

#!/bin/bash
# Setup script for the Claude Code cloud environment "warehouse-platform".
# Paste into the environment's Setup script field (claude.ai/code > environment
# selector > settings). Runs as root on Ubuntu 24.04 before Claude starts; the
# resulting filesystem is cached, so keep it under about five minutes.
#
# Network access: Custom, default list included, plus:
#   quay.io, cdn01.quay.io, cdn02.quay.io, cdn03.quay.io   (Keycloak image)
#   ghcr.io, pkg-containers.githubusercontent.com          (uv image)

command -v uv >/dev/null || pip install --break-system-packages uv || true
command -v just >/dev/null || uv tool install rust-just || true

(pgrep dockerd >/dev/null || (dockerd >/tmp/dockerd.log 2>&1 &))
sleep 5

# Pre-pull images so they are in the cached snapshot.
for img in postgres:17 clickhouse/clickhouse-server:25.8 \
           quay.io/keycloak/keycloak:26.4 python:3.13-slim \
           ghcr.io/astral-sh/uv:0.11; do
  docker pull "$img" &
done
wait

exit 0

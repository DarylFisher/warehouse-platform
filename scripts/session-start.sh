#!/bin/bash
# SessionStart hook (cloud and local): make sure Python dependencies are in
# place and, in cloud sessions, that the Docker daemon is running.
# Containers are not started here; run `just up` or `just deps` when needed.

cd "$(dirname "$0")/../backend" || exit 0
uv sync --quiet >/dev/null 2>&1 || echo "session-start: uv sync failed; run it manually"

if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ] && ! pgrep dockerd >/dev/null; then
  (dockerd >/tmp/dockerd.log 2>&1 &)
fi
exit 0

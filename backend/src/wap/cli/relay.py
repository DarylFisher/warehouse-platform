"""Outbox relay worker: polls for committed events and ships them to ClickHouse.

python -m wap.cli.relay            # run until stopped
python -m wap.cli.relay --once     # one pass, then exit (scripts, tests)
"""

import logging
import signal
import sys
import time

import psycopg

from wap.clickhouse import create_client
from wap.config import get_settings
from wap.kernel.outbox import relay_batch

log = logging.getLogger("wap.relay")

IDLE_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0


def run(once: bool = False) -> None:
    settings = get_settings()
    stopping = False

    def stop(*_: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    backoff = IDLE_SECONDS
    client = create_client(settings)
    try:
        with psycopg.connect(settings.relay_database_url, autocommit=True) as conn:
            while not stopping:
                result = relay_batch(conn, client, settings.relay_batch_size)
                if result.published:
                    log.info("published %d event(s)", result.published)
                if result.failed:
                    log.warning("could not publish %d event(s); retrying", result.failed)
                    backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                else:
                    backoff = IDLE_SECONDS
                if once and not result.published:
                    break
                if result.failed or not result.published:
                    time.sleep(backoff)
    finally:
        client.close()


def main(argv: list[str]) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    run(once="--once" in argv)


if __name__ == "__main__":
    main(sys.argv[1:])

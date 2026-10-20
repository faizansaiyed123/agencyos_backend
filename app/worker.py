"""Standalone job worker process: `python -m app.worker`.

Polls for claimable jobs and dispatches them via app.platform.jobs. Multiple
instances of this process can run concurrently (e.g. one per container
replica) — that's the entire reason claim_jobs() uses SKIP LOCKED. No shared
in-memory state, no leader election, no external coordination needed.
"""

import signal
import time
from types import FrameType

import structlog

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.logging import configure_logging
from app.modules.billing import jobs as billing_jobs
from app.modules.identity import jobs as identity_jobs
from app.modules.proposals import jobs as proposals_jobs
from app.platform import webhooks as webhooks_platform
from app.platform.jobs import run_worker_once

configure_logging()
identity_jobs.register()
billing_jobs.register()
proposals_jobs.register()
webhooks_platform.register()
log = structlog.get_logger()

_shutdown_requested = False


def _handle_shutdown(signum: int, frame: FrameType | None) -> None:
    global _shutdown_requested
    log.info("worker_shutdown_requested", signal=signum)
    _shutdown_requested = True


def main(*, poll_interval_seconds: float = 2.0, batch_size: int = 10) -> None:
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)
    get_settings()  # fail fast on bad config before entering the loop
    session_factory = get_sessionmaker()

    log.info("worker_started", poll_interval_seconds=poll_interval_seconds, batch_size=batch_size)
    while not _shutdown_requested:
        with session_factory() as db:
            processed = run_worker_once(db, batch_size=batch_size)
        if processed == 0:
            time.sleep(poll_interval_seconds)
    log.info("worker_stopped")


if __name__ == "__main__":
    main()

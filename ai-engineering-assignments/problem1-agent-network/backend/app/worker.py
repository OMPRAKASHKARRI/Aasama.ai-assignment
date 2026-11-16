"""Run a worker:  python -m app.worker   (equivalent to ``rq worker`` bound to our queue/redis)."""
from __future__ import annotations

import logging

from rq import Worker

from app.config import get_settings
from app.services.queueing import get_queue, get_redis


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    worker = Worker([get_queue()], connection=get_redis())
    worker.work(with_scheduler=True)  # scheduler is required for delayed retry intervals


if __name__ == "__main__":
    get_settings()
    main()

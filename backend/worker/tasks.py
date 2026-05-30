"""
Celery task definitions — the worker entry-point.

This is the "routes" equivalent for the worker: it receives messages,
manages the DB session lifecycle, and delegates to the service layer.

Run from project root:
    celery -A backend.worker.tasks:celery_app worker --loglevel=info --pool=solo
"""

import logging
import os
from typing import Any

from celery import Celery

from backend.db.models import SessionLocal
from backend.worker import services

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("loganalyzer.worker.tasks")

# ------------------------------------------------------------------
# Celery app
# ------------------------------------------------------------------
_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "loganalyzer",
    broker=_REDIS_URL,
    backend=_REDIS_URL,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
)


# ------------------------------------------------------------------
# Tasks
# ------------------------------------------------------------------
@celery_app.task(name="process_session", bind=True, max_retries=2)
def process_session(self: Any, session_id: str) -> None:
    """
    Entry-point for background analysis.

    Manages the DB session lifecycle and delegates all logic to
    ``backend.worker.services.run_analysis``.
    """
    db = SessionLocal()
    try:
        services.run_analysis(session_id, db)
    finally:
        db.close()

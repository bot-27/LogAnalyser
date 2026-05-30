"""
Service layer — business logic for the API.

Controllers call services; services call repositories.
Services never import from routes or controllers.
"""

import logging
import os
import uuid
from typing import Any

from sqlalchemy.orm import Session

from api import repositories
from api.exceptions import NotFoundError, ServiceError
from worker.tasks import process_session

logger = logging.getLogger("loganalyzer.api.services")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")


def create_analysis(
    file_data: list[tuple[str, bytes]],
    db: Session,
) -> str:
    """
    Persist uploaded files to disk, create DB records, and dispatch
    the Celery background task.

    Parameters
    ----------
    file_data : list of (filename, raw_bytes) tuples — already validated
                by the controller layer.
    db        : active SQLAlchemy session (managed by the routes layer).

    Returns
    -------
    session_id : str
    """
    session_id = str(uuid.uuid4())

    try:
        repositories.create_session(db, session_id)

        session_dir = os.path.join(_DATA_DIR, session_id)
        os.makedirs(session_dir, exist_ok=True)

        for filename, content in file_data:
            safe_name = filename or f"{uuid.uuid4()}.log"
            dest = os.path.join(session_dir, safe_name)
            with open(dest, "wb") as fh:
                fh.write(content)
            repositories.add_log_file(db, session_id, dest)

        repositories.commit(db)
    except Exception as exc:
        repositories.rollback(db)
        logger.exception("Failed to create analysis session")
        raise ServiceError(str(exc)) from exc

    process_session.delay(session_id)
    logger.info("Session %s queued with %d file(s)", session_id, len(file_data))
    return session_id


def get_session_status(session_id: str, db: Session) -> dict[str, Any]:
    """
    Fetch current session state from the repository.

    Raises NotFoundError if the session does not exist.
    """
    session = repositories.get_session_by_id(db, session_id)
    if session is None:
        raise NotFoundError(f"Session {session_id} not found")

    return {
        "session_id": session.id,
        "status": session.status,
        "verdict": session.verdict,
        "graph_data": session.graph_data,
    }

"""
Repository layer — all database operations for the API service.

This is the ONLY layer that touches SQLAlchemy queries.
Services call repositories; repositories never call upward.
"""

import uuid

from sqlalchemy.orm import Session

from backend.db.models import AnalysisSession, LogFile


def create_session(db: Session, session_id: str) -> AnalysisSession:
    """Insert a new AnalysisSession with status PENDING."""
    session = AnalysisSession(id=session_id, status="PENDING")
    db.add(session)
    return session


def add_log_file(
    db: Session,
    session_id: str,
    file_path: str,
) -> LogFile:
    """Insert a new LogFile record linked to a session."""
    log_file = LogFile(
        id=str(uuid.uuid4()),
        session_id=session_id,
        file_path=file_path,
    )
    db.add(log_file)
    return log_file


def get_session_by_id(db: Session, session_id: str) -> AnalysisSession | None:
    """Return an AnalysisSession or None."""
    return (
        db.query(AnalysisSession)
        .filter(AnalysisSession.id == session_id)
        .first()
    )


def update_status(db: Session, session: AnalysisSession, status: str) -> None:
    session.status = status
    db.add(session)


def commit(db: Session) -> None:
    db.commit()


def rollback(db: Session) -> None:
    db.rollback()

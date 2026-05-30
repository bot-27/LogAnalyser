"""
Repository layer — all database operations for the worker service.

Services call repositories; repositories never call upward.
"""

from typing import Any

from sqlalchemy.orm import Session

from backend.db.models import AnalysisSession, LogFile


def get_session_by_id(db: Session, session_id: str) -> AnalysisSession | None:
    """Return an AnalysisSession or None."""
    return (
        db.query(AnalysisSession)
        .filter(AnalysisSession.id == session_id)
        .first()
    )


def get_log_files(db: Session, session_id: str) -> list[LogFile]:
    """Return all LogFile records linked to a session."""
    return (
        db.query(LogFile)
        .filter(LogFile.session_id == session_id)
        .all()
    )


def update_status(db: Session, session: AnalysisSession, status: str) -> None:
    """Set the session status and commit."""
    session.status = status
    db.commit()


def save_result(
    db: Session,
    session: AnalysisSession,
    *,
    verdict: str,
    graph_data: dict[str, Any],
    status: str = "COMPLETED",
) -> None:
    """Write analysis results and commit."""
    session.verdict = verdict
    session.graph_data = graph_data
    session.status = status
    db.commit()


def rollback(db: Session) -> None:
    db.rollback()

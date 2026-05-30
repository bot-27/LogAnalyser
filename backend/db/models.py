"""
Shared database models and session factory.

Both the API and worker services import from this module.
Run all services from the project root so the package import ``db.models`` resolves.
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Generator

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    JSON,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import (
    Session,
    declarative_base,
    relationship,
    sessionmaker,
)

# ---------------------------------------------------------------------------
# Paths – anchored to the project root (parent of this package)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH = os.path.join(_PROJECT_ROOT, "data", "loganalyzer.db")
os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)

DATABASE_URL = f"sqlite:///{_DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def generate_uuid() -> str:
    """Return a new UUID4 string."""
    return str(uuid.uuid4())


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session and guarantee cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class AnalysisSession(Base):  # type: ignore[misc]
    __tablename__ = "analysis_sessions"

    id = Column(String, primary_key=True, default=generate_uuid)
    status = Column(String(32), nullable=False, default="PENDING")
    verdict = Column(Text, nullable=True)
    graph_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    log_files = relationship(
        "LogFile",
        back_populates="session",
        cascade="all, delete-orphan",
    )


class LogFile(Base):  # type: ignore[misc]
    __tablename__ = "log_files"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("analysis_sessions.id"), nullable=False)
    file_path = Column(String(512), nullable=False)

    session = relationship("AnalysisSession", back_populates="log_files")


# ---------------------------------------------------------------------------
# Create tables on import (idempotent)
# ---------------------------------------------------------------------------
Base.metadata.create_all(bind=engine)

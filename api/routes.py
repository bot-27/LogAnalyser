"""
Routes layer — FastAPI endpoint definitions.

This layer ONLY wires HTTP concerns (request extraction, response codes,
exception-to-HTTP mapping). All logic is delegated to controllers.
"""

import logging
import os

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from api import controllers
from api.exceptions import NotFoundError, ServiceError, ValidationError
from db.models import get_db

logger = logging.getLogger("loganalyzer.api.routes")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FRONTEND_DIR = os.path.join(_PROJECT_ROOT, "frontend")

router = APIRouter()


# ------------------------------------------------------------------
# HTML entry-point
# ------------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
async def root() -> str:
    """Serve the single-page frontend."""
    html_path = os.path.join(_FRONTEND_DIR, "index.html")
    with open(html_path, "r", encoding="utf-8") as fh:
        return fh.read()


# ------------------------------------------------------------------
# Upload
# ------------------------------------------------------------------
@router.post("/upload", status_code=202)
async def upload(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> dict:
    """Accept multiple log files and return a session_id."""
    try:
        return await controllers.handle_upload(files, db)
    except ValidationError as exc:
        return JSONResponse(  # type: ignore[return-value]
            status_code=exc.status_code,
            content={"error": exc.message},
        )
    except ServiceError as exc:
        return JSONResponse(  # type: ignore[return-value]
            status_code=500,
            content={"error": exc.message},
        )
    except Exception as exc:
        logger.exception("Unhandled error in /upload")
        return JSONResponse(  # type: ignore[return-value]
            status_code=500,
            content={"error": str(exc)},
        )


# ------------------------------------------------------------------
# Status polling
# ------------------------------------------------------------------
@router.get("/status/{session_id}")
async def status(
    session_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """Return session status, verdict, and graph_data."""
    try:
        return controllers.handle_get_status(session_id, db)
    except ValidationError as exc:
        return JSONResponse(  # type: ignore[return-value]
            status_code=exc.status_code,
            content={"error": exc.message},
        )
    except NotFoundError as exc:
        return JSONResponse(  # type: ignore[return-value]
            status_code=404,
            content={"error": exc.message},
        )

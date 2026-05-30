"""
Routes layer — FastAPI endpoint definitions.

This layer ONLY wires HTTP concerns (request extraction, response codes,
exception-to-HTTP mapping). All logic is delegated to controllers.
"""

import logging
import os

from fastapi import APIRouter, Depends, File, UploadFile, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from backend.api import controllers
from backend.api.exceptions import NotFoundError, ServiceError, ValidationError
from backend.db.models import get_db

logger = logging.getLogger("loganalyzer.api.routes")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> dict:
    """Accept multiple log files and return a session_id."""
    try:
        return await controllers.handle_upload(files, background_tasks, db)
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


# ------------------------------------------------------------------
# Knowledge Graph and Models routes
# ------------------------------------------------------------------
from fastapi import Body

@router.get("/models")
async def list_models() -> dict:
    """List available Ollama models."""
    return await controllers.handle_list_models()

@router.get("/knowledge-graph")
async def get_kg_summary(service_name: str | None = None) -> dict:
    """Get the full knowledge graph summary."""
    return controllers.handle_kg_summary(service_name)

@router.get("/knowledge-graph/data")
async def get_kg_data(service_name: str | None = None) -> dict:
    """Get the full knowledge graph data."""
    return controllers.handle_kg_data(service_name)

@router.post("/knowledge-graph/insight")
async def add_insight(body: dict = Body(...)) -> dict:
    """Add a developer insight to the knowledge graph."""
    insight_text = body.get("insight", "").strip()
    related = body.get("related_entities", [])
    service_name = body.get("service_name")
    try:
        return await controllers.handle_kg_insight(insight_text, related, service_name)
    except ValidationError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message}) # type: ignore[return-value]

@router.post("/knowledge-graph/explain")
async def explain_knowledge_graph(body: dict = Body(default={})) -> dict:
    """Generate an AI SRE explanation of the knowledge graph contents."""
    model = body.get("model")
    service_name = body.get("service_name")
    return await controllers.handle_kg_explain(model, service_name)

@router.post("/knowledge-graph")
async def restructure_knowledge_graph(body: dict = Body(default={})) -> dict:
    """Restructure the knowledge graph."""
    instructions = body.get("instructions", "Auto-restructure: merge duplicates and clean up.")
    model = body.get("model")
    service_name = body.get("service_name")
    return await controllers.handle_kg_restructure(instructions, model, service_name)

@router.delete("/knowledge-graph")
async def clear_knowledge_graph(service_name: str | None = None) -> dict:
    """Clear the knowledge graph."""
    return controllers.handle_kg_clear(service_name)

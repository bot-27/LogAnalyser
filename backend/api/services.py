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

from backend.api import repositories
from backend.api.exceptions import NotFoundError, ServiceError
from fastapi import BackgroundTasks

from backend.db.models import SessionLocal
from backend.worker import services as worker_services

logger = logging.getLogger("loganalyzer.api.services")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")


def process_session_background(session_id: str) -> None:
    db = SessionLocal()
    try:
        worker_services.run_analysis(session_id, db)
    finally:
        db.close()

def create_analysis(
    file_data: list[tuple[str, bytes]],
    background_tasks: BackgroundTasks,
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

    background_tasks.add_task(process_session_background, session_id)
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

def cancel_session(session_id: str, db: Session) -> dict[str, Any]:
    session = repositories.get_session_by_id(db, session_id)
    if session is None:
        raise NotFoundError(f"Session {session_id} not found")
    
    if session.status in ("PENDING", "PROCESSING"):
        repositories.update_status(db, session, "CANCELLED")
        repositories.commit(db)
        
    return {"session_id": session.id, "status": "CANCELLED"}

# ------------------------------------------------------------------
# Knowledge Graph and Models services
# ------------------------------------------------------------------
import httpx
from backend.knowledge_graph import KnowledgeGraphManager

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
KNOWLEDGE_GRAPH_DIR = os.getenv("KNOWLEDGE_GRAPH_DIR", os.path.join(_PROJECT_ROOT, "knowledge_graph"))

kg_managers: dict[str, KnowledgeGraphManager] = {}

def get_kg_manager(service_name: str | None) -> KnowledgeGraphManager:
    if not service_name:
        service_name = "default"
    
    safe_name = "".join([c for c in service_name if c.isalnum() or c in ('-', '_')])
    if not safe_name:
        safe_name = "default"
        
    if safe_name not in kg_managers:
        storage_dir = os.path.join(KNOWLEDGE_GRAPH_DIR, safe_name)
        kg_managers[safe_name] = KnowledgeGraphManager(
            storage_dir=storage_dir,
            ollama_base_url=OLLAMA_BASE_URL,
            default_model=DEFAULT_MODEL,
        )
    return kg_managers[safe_name]


async def list_models(max_file_size_mb: int) -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            resp.raise_for_status()
            data = resp.json()

        models = []
        for m in data.get("models", []):
            models.append({
                "name": m.get("name", ""),
                "size": m.get("size", 0),
                "modified_at": m.get("modified_at", ""),
            })

        return {
            "models": models,
            "default": DEFAULT_MODEL,
            "max_file_size_mb": max_file_size_mb,
            "ollama_connected": True
        }

    except Exception as e:
        logger.warning("Could not connect to Ollama: %s", e)
        return {
            "models": [],
            "default": DEFAULT_MODEL,
            "max_file_size_mb": max_file_size_mb,
            "ollama_connected": False,
            "error": "Cannot connect to Ollama. Is it running?"
        }

def get_kg_data(service_name: str | None) -> dict:
    kg_manager = get_kg_manager(service_name)
    return kg_manager.get_graph_data()

def get_kg_summary(service_name: str | None) -> dict:
    kg_manager = get_kg_manager(service_name)
    return kg_manager.get_graph_summary()

async def add_kg_insight(insight_text: str, related_entities: list[str], service_name: str | None) -> dict:
    kg_manager = get_kg_manager(service_name)
    return await kg_manager.add_developer_insight(insight_text, related_entities)

async def explain_kg(model: str | None, service_name: str | None) -> dict:
    kg_manager = get_kg_manager(service_name)
    graph_data = kg_manager.get_graph_data()
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])
    
    if not nodes:
        return {"explanation": "The knowledge graph is currently empty. Analyze some logs first to populate it!"}
        
    nodes_str = "\n".join([
        f"- Node '{n['id']}' ({n.get('type', 'unknown')}): {n.get('description', 'No description')} (Seen {n.get('observation_count', 1)} times)"
        for n in nodes
    ])
    
    edges_str = "\n".join([
        f"- Relationship: '{e['source']}' {e.get('type', 'relates to')} -> '{e['target']}'"
        for e in edges
    ])
    
    prompt = (
        "You are a principal site reliability engineer.\n\n"
        "Analyze the following Knowledge Graph which represents the collective state of errors, services, root causes, and fixes extracted from application logs:\n\n"
        "### Nodes (Entities):\n"
        f"{nodes_str}\n\n"
        "### Edges (Relationships):\n"
        f"{edges_str}\n\n"
        "Provide a high-level, structured SRE summary explaining:\n"
        "1. What is the overall state of the system based on this knowledge?\n"
        "2. What are the key recurring issues or failures, and their known root causes?\n"
        "3. What are the best recommended actions or fixes discovered so far?\n\n"
        "Respond in clear markdown with headers (##). Be concise and professional."
    )
    
    from langchain_ollama import ChatOllama
    llm = ChatOllama(
        model=model or DEFAULT_MODEL,
        temperature=0.3,
        base_url=OLLAMA_BASE_URL,
    )
    
    result = await llm.ainvoke(prompt)
    return {"explanation": result.content}

async def restructure_kg(instructions: str, model: str | None, service_name: str | None) -> dict:
    kg_manager = get_kg_manager(service_name)
    return await kg_manager.restructure(instructions=instructions, model=model)

def clear_kg(service_name: str | None) -> dict:
    kg_manager = get_kg_manager(service_name)
    return kg_manager.clear()

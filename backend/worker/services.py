"""
Service layer — business logic for the worker.

Tasks (entry-point) call services; services call repositories.
Services never import from tasks.
"""

import logging
import os

from sqlalchemy.orm import Session

from backend.worker import repositories

logger = logging.getLogger("loganalyzer.worker.services")


# ------------------------------------------------------------------
# Dummy analysis helpers (swap for real Ollama / graphiffy calls)
# ------------------------------------------------------------------
def _dummy_ollama_analyze(text: str) -> str:
    """Simulate Ollama LLM analysis on aggregated log text."""
    lines = text.strip().splitlines()
    error_count = sum(
        1 for line in lines if "error" in line.lower() or "fail" in line.lower()
    )
    warn_count = sum(1 for line in lines if "warn" in line.lower())
    return (
        f"## Analysis Summary\n\n"
        f"Processed **{len(lines)}** log lines.\n\n"
        f"- **Errors / Failures detected:** {error_count}\n"
        f"- **Warnings detected:** {warn_count}\n\n"
        f"### Root Cause\n"
        f"Simulated root-cause analysis placeholder.\n\n"
        f"### Recommendations\n"
        f"- Review error-producing services\n"
        f"- Check resource utilisation around failure timestamps\n"
    )


def _dummy_graphify(text: str) -> dict[str, list[dict[str, str]]]:
    """Simulate graph data extraction from log content."""
    tokens: set[str] = set()
    for line in text.splitlines():
        lower = line.lower()
        if "error" in lower or "fail" in lower or "exception" in lower:
            for word in line.split():
                clean = word.strip("[]():,\"'").lower()
                if len(clean) > 3 and clean.isalpha():
                    tokens.add(clean)

    node_list = sorted(tokens)[:20]
    nodes: list[dict[str, str]] = [
        {"id": tok, "label": tok, "type": "keyword"} for tok in node_list
    ]
    edges: list[dict[str, str]] = [
        {"source": node_list[i], "target": node_list[i + 1], "relation": "co-occurs"}
        for i in range(len(node_list) - 1)
    ]
    return {"nodes": nodes, "edges": edges}


# ------------------------------------------------------------------
# Core analysis orchestration
# ------------------------------------------------------------------
import asyncio
from backend.app import analyze_logs, get_kg_manager

def run_analysis(session_id: str, db: Session) -> None:
    """
    Full analysis pipeline:
      1. Mark session as PROCESSING  (repository)
      2. Read all linked log files from disk
      3. Run analysis via LangChain/Ollama
      4. Persist results  (repository)
    """
    session = repositories.get_session_by_id(db, session_id)
    if session is None:
        logger.error("Session %s not found — skipping", session_id)
        return

    try:
        repositories.update_status(db, session, "PROCESSING")

        log_files = repositories.get_log_files(db, session_id)

        aggregated: list[str] = []
        filenames: list[str] = []
        for lf in log_files:
            try:
                with open(lf.file_path, "r", encoding="utf-8", errors="ignore") as fh:
                    aggregated.append(fh.read())
                    filenames.append(os.path.basename(lf.file_path))
            except OSError as err:
                logger.warning("Could not read %s: %s", lf.file_path, err)

        combined_text = "\n\n--- FILE BOUNDARY ---\n\n".join(aggregated)
        combined_filename = ", ".join(filenames)

        # Retrieve knowledge graph manager (use default for now)
        kg_manager = get_kg_manager("default")

        # Run async analysis pipeline synchronously in this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            verdict, context_used, msg = loop.run_until_complete(
                analyze_logs(combined_text, model=None, use_kg=True, system_info=None, kg_manager=kg_manager)
            )
            # Update knowledge graph with the insights
            loop.run_until_complete(
                kg_manager.add_analysis_entities(verdict, combined_filename, model=None)
            )
        finally:
            loop.close()

        graph_data = kg_manager.get_graph_data()

        repositories.save_result(
            db, session, verdict=verdict, graph_data=graph_data
        )
        logger.info("Session %s completed successfully", session_id)

    except Exception as exc:
        repositories.rollback(db)
        logger.exception("Analysis failed for session %s", session_id)
        # Re-fetch session after rollback to write the failure state
        failed = repositories.get_session_by_id(db, session_id)
        if failed is not None:
            repositories.save_result(
                db,
                failed,
                verdict=f"Processing error: {exc}",
                graph_data={"nodes": [], "edges": []},
                status="FAILED",
            )

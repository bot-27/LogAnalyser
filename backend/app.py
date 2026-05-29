"""
LogAnalyzer Agent — FastAPI Backend
====================================
AI-powered log analysis using LangChain + Ollama (local LLM).
Now with persistent knowledge graph for contextual analysis.

Based on: https://share.google/8pdQfnkCgbNa8NNZU
Architecture: FastAPI receives uploaded log file → splits into chunks →
             queries knowledge graph for prior context →
             sends each chunk to local LLM with SRE prompt → returns combined analysis →
             extracts entities into the knowledge graph for future use.
"""

import logging
import os
import httpx

# pyrefly: ignore [missing-import]
from fastapi import FastAPI, UploadFile, File, Body, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import ChatOllama
from dotenv import load_dotenv

from knowledge_graph import KnowledgeGraphManager

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("loganalyzer")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "10"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {".txt", ".log", ".csv"}
KNOWLEDGE_GRAPH_DIR = os.getenv("KNOWLEDGE_GRAPH_DIR", "./knowledge_graph")

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(title="Log Analyzer Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Knowledge Graph
# ---------------------------------------------------------------------------
kg_manager = KnowledgeGraphManager(
    storage_dir=KNOWLEDGE_GRAPH_DIR,
    ollama_base_url=OLLAMA_BASE_URL,
    default_model=DEFAULT_MODEL,
)

# ---------------------------------------------------------------------------
# Prompt Template (from the article — SRE role with 4 analysis points)
# ---------------------------------------------------------------------------
log_analysis_prompt_text = """
You are a senior site reliability engineer.

{system_section}
Analyze the following application logs.

1. Identify the main errors or failures.
2. Explain the likely root cause in simple terms.
3. Suggest practical next steps to fix or investigate.
4. Mention any suspicious patterns or repeated issues.

{prior_knowledge}

Logs:
{log_data}

Respond in clear paragraphs. Use markdown formatting with headers (##) for each section.
Avoid jargon where possible.
"""


# ---------------------------------------------------------------------------
# Log Splitting (from the article — chunk_size=2000, chunk_overlap=200)
# ---------------------------------------------------------------------------
def split_logs(log_text: str):
    """Split log text into manageable chunks."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=4000,
        chunk_overlap=400,
    )
    return splitter.split_text(log_text)


# ---------------------------------------------------------------------------
# Log Analysis (enhanced with knowledge graph context)
# ---------------------------------------------------------------------------
async def analyze_logs(log_text: str, model: str | None = None, use_kg: bool = True, system_info: str | None = None):
    """Analyze logs by splitting and processing each chunk, with KG context and optional system info."""
    selected_model = model or DEFAULT_MODEL

    llm = ChatOllama(
        model=selected_model,
        temperature=0.2,
        base_url=OLLAMA_BASE_URL,
    )

    # Retrieve relevant context from knowledge graph if enabled
    if use_kg:
        prior_knowledge = kg_manager.get_relevant_context(log_text)
        context_used = len(prior_knowledge) > 0
    else:
        prior_knowledge = ""
        context_used = False

    if prior_knowledge:
        prior_section = (
            "The following prior knowledge from previous analyses may be relevant. "
            "Use it to provide deeper insights if applicable:\n\n"
            + prior_knowledge
            + "\n"
        )
    else:
        prior_section = ""

    if system_info:
        system_section = f"System Information Context:\n{system_info}\n\n"
    else:
        system_section = ""

    chunks = split_logs(log_text)
    logger.info("Split logs into %d chunk(s), using model '%s'", len(chunks), selected_model)

    combined_analysis = []

    for i, chunk in enumerate(chunks, 1):
        logger.info("Analyzing chunk %d/%d …", i, len(chunks))
        formatted_prompt = log_analysis_prompt_text.format(
            log_data=chunk,
            prior_knowledge=prior_section,
            system_section=system_section,
        )
        result = await llm.ainvoke(formatted_prompt)
        combined_analysis.append(result.content)

    full_analysis = "\n\n---\n\n".join(combined_analysis)

    return full_analysis, context_used


def preprocess_log_text(log_text: str, max_chars: int = 10000) -> tuple[str, bool, str]:
    """
    Preprocess log text. If it exceeds max_chars, filter it to keep only lines with
    keywords (and their immediate context) to avoid overloading the LLM and causing timeouts.
    """
    import re
    orig_len = len(log_text)
    if orig_len <= max_chars:
        return log_text, False, f"Original file ({orig_len / 1024:.1f} KB)"

    lines = log_text.splitlines()
    num_lines = len(lines)
    
    # Compile a fast case-insensitive regex for error-related keywords
    error_pattern = re.compile(
        r"error|fail|exception|critical|fatal|warn|severe|stacktrace|traceback|caused by",
        re.IGNORECASE
    )
    matched_indices = set()
    
    for idx, line in enumerate(lines):
        if error_pattern.search(line):
            # Add context: 2 lines before and 2 lines after
            start = max(0, idx - 2)
            end = min(num_lines, idx + 3)
            for j in range(start, end):
                matched_indices.add(j)
                
    # If no lines match (highly unusual for logs), fall back to taking the tail of the log
    if not matched_indices:
        tail_text = "\n".join(lines[-1000:])
        if len(tail_text) > max_chars:
            tail_text = tail_text[-max_chars:]
        return tail_text, True, f"Large file tail (no errors found, showing last {len(tail_text)/1024:.1f} KB)"

    # Build the filtered text
    sorted_indices = sorted(list(matched_indices))
    
    # We insert separators [...] where there are gaps in matching context lines
    filtered_parts = []
    prev_idx = -2
    for idx in sorted_indices:
        if prev_idx != -2 and idx > prev_idx + 1:
            filtered_parts.append("[...]")
        filtered_parts.append(lines[idx])
        prev_idx = idx
        
    filtered_text = "\n".join(filtered_parts)
    
    # If filtered text is still larger than max_chars, take the tail of it
    if len(filtered_text) > max_chars:
        filtered_text = "[...]\n" + filtered_text[-max_chars:]
        
    reduction_pct = (1 - len(filtered_text) / orig_len) * 100
    status_msg = f"Filtered {orig_len / 1024 / 1024:.1f} MB down to {len(filtered_text) / 1024:.1f} KB of error context ({reduction_pct:.1f}% reduction)"
    return filtered_text, True, status_msg


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main HTML page."""
    html_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


async def run_kg_update_background(insights: str, filename: str, model: str | None):
    """Asynchronously update the knowledge graph in the background."""
    try:
        await kg_manager.add_analysis_entities(
            analysis_text=insights,
            filename=filename,
            model=model,
        )
    except Exception as kg_err:
        logger.warning("Knowledge graph background update failed: %s", kg_err)


@app.post("/analyze")
async def analyze_log_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    system_info: UploadFile | None = File(None),
    model: str | None = None,
    use_kg: bool = True,
):
    """Analyze uploaded log file and update knowledge graph."""
    # Validate file extension
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        return JSONResponse(
            status_code=400,
            content={
                "error": f"Unsupported file type '{ext}'. "
                         f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            },
        )

    try:
        content = await file.read()

        # Validate file size
        if len(content) > MAX_FILE_SIZE_BYTES:
            return JSONResponse(
                status_code=400,
                content={
                    "error": f"File too large ({len(content) / 1024 / 1024:.1f} MB). "
                             f"Maximum allowed: {MAX_FILE_SIZE_MB} MB."
                },
            )

        log_text = content.decode("utf-8", errors="ignore")

        if not log_text.strip():
            return JSONResponse(
                status_code=400,
                content={"error": "Log file is empty"},
            )

        logger.info(
            "Received file '%s' (%d bytes, %d lines)",
            filename,
            len(content),
            log_text.count("\n") + 1,
        )

        # Handle optional system info file
        system_info_text = None
        if system_info is not None and system_info.filename:
            try:
                sys_info_content = await system_info.read()
                if len(sys_info_content) > 5 * 1024 * 1024:
                    return JSONResponse(
                        status_code=400,
                        content={"error": "System info file too large. Maximum allowed: 5 MB."},
                    )
                if sys_info_content.strip():
                    system_info_text = sys_info_content.decode("utf-8", errors="ignore")
                    logger.info(
                        "Received optional system info file '%s' (%d bytes)",
                        system_info.filename,
                        len(sys_info_content)
                    )
            except Exception as sys_err:
                logger.warning("Failed to read optional system info file: %s", sys_err)

        # Preprocess / filter large logs to prevent timeouts and LLM thrashing
        processed_text, was_filtered, filter_status = preprocess_log_text(log_text)
        if was_filtered:
            logger.info("Log pre-filtering: %s", filter_status)

        insights, context_used = await analyze_logs(processed_text, model, use_kg, system_info=system_info_text)

        if was_filtered:
            filter_note = (
                f"> [!NOTE]\n"
                f"> **Log Pre-filtering Applied**: The log file was too large ({len(content) / 1024 / 1024:.1f} MB) "
                f"to process sequentially in full. It was automatically filtered down to {len(processed_text) / 1024:.1f} KB "
                f"of relevant error, warning, and stacktrace contexts to prevent timeouts and optimize analysis.\n\n"
            )
            insights = filter_note + insights

        if system_info_text:
            system_note = (
                f"> [!TIP]\n"
                f"> **System Context Provided**: Analysis is informed by environment specifications from `{system_info.filename}`.\n\n"
            )
            insights = system_note + insights

        # Extract entities from analysis and add to knowledge graph asynchronously in background
        background_tasks.add_task(
            run_kg_update_background,
            insights=insights,
            filename=filename,
            model=model,
        )

        return {
            "analysis": insights,
            "knowledge_graph": {
                "context_used": context_used,
                "update": {"status": "queued"},
                "summary": kg_manager.get_graph_summary(),
            },
        }

    except Exception as e:
        logger.exception("Error analyzing logs")
        return JSONResponse(
            status_code=500,
            content={"error": f"Error analyzing logs: {str(e)}"},
        )


# ---------------------------------------------------------------------------
# Knowledge Graph API Endpoints
# ---------------------------------------------------------------------------
@app.get("/knowledge-graph")
async def get_knowledge_graph_summary():
    """Get knowledge graph summary and statistics."""
    return kg_manager.get_graph_summary()


@app.get("/knowledge-graph/data")
async def get_knowledge_graph_data():
    """Get full graph data for visualization."""
    return kg_manager.get_graph_data()


@app.post("/knowledge-graph/restructure")
async def restructure_knowledge_graph(
    body: dict = Body(default={}),
):
    """Restructure the knowledge graph with optional instructions."""
    instructions = body.get("instructions", "Auto-restructure: merge duplicates and clean up.")
    model = body.get("model")
    try:
        result = await kg_manager.restructure(instructions=instructions, model=model)
        return result
    except Exception as e:
        logger.exception("Error restructuring knowledge graph")
        return JSONResponse(
            status_code=500,
            content={"error": f"Restructure failed: {str(e)}"},
        )


@app.post("/knowledge-graph/insight")
async def add_insight(
    body: dict = Body(...),
):
    """Add a developer insight to the knowledge graph."""
    insight_text = body.get("insight", "").strip()
    if not insight_text:
        return JSONResponse(
            status_code=400,
            content={"error": "Insight text is required"},
        )

    related = body.get("related_entities", [])
    try:
        result = await kg_manager.add_developer_insight(
            insight_text=insight_text,
            related_entities=related,
        )
        return result
    except Exception as e:
        logger.exception("Error adding insight")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to add insight: {str(e)}"},
        )


@app.post("/knowledge-graph/explain")
async def explain_knowledge_graph(
    body: dict = Body(default={}),
):
    """Generate an AI SRE explanation of the knowledge graph contents."""
    model = body.get("model")
    try:
        # Format the graph data into a text description
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
        
        llm = ChatOllama(
            model=model or DEFAULT_MODEL,
            temperature=0.3,
            base_url=OLLAMA_BASE_URL,
        )
        
        result = await llm.ainvoke(prompt)
        return {"explanation": result.content}
        
    except Exception as e:
        logger.exception("Error explaining knowledge graph")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to generate graph explanation: {str(e)}"},
        )


@app.delete("/knowledge-graph")
async def clear_knowledge_graph():
    """Clear the knowledge graph (creates backup first)."""
    return kg_manager.clear()


# ---------------------------------------------------------------------------
# Ollama Model & Health Endpoints
# ---------------------------------------------------------------------------
@app.get("/models")
async def list_models():
    """List available Ollama models."""
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
            "max_file_size_mb": MAX_FILE_SIZE_MB,
            "ollama_connected": True
        }

    except Exception as e:
        logger.warning("Could not connect to Ollama: %s", e)
        return {
            "models": [],
            "default": DEFAULT_MODEL,
            "max_file_size_mb": MAX_FILE_SIZE_MB,
            "ollama_connected": False,
            "error": "Cannot connect to Ollama. Is it running?"
        }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            ollama_ok = resp.status_code == 200
    except Exception:
        pass

    kg_summary = kg_manager.get_graph_summary()

    return {
        "status": "healthy" if ollama_ok else "degraded",
        "ollama_connected": ollama_ok,
        "ollama_url": OLLAMA_BASE_URL,
        "default_model": DEFAULT_MODEL,
        "knowledge_graph": kg_summary,
    }


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    logger.info("Starting LogAnalyzer on port %d", port)
    uvicorn.run(app, host="0.0.0.0", port=port)

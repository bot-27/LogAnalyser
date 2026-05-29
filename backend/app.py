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

from fastapi import FastAPI, UploadFile, File, Body
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
        chunk_size=2000,
        chunk_overlap=200,
    )
    return splitter.split_text(log_text)


# ---------------------------------------------------------------------------
# Log Analysis (enhanced with knowledge graph context)
# ---------------------------------------------------------------------------
async def analyze_logs(log_text: str, model: str | None = None):
    """Analyze logs by splitting and processing each chunk, with KG context."""
    selected_model = model or DEFAULT_MODEL

    llm = ChatOllama(
        model=selected_model,
        temperature=0.2,
        base_url=OLLAMA_BASE_URL,
    )

    # Retrieve relevant context from knowledge graph
    prior_knowledge = kg_manager.get_relevant_context(log_text)
    context_used = len(prior_knowledge) > 0

    if prior_knowledge:
        prior_section = (
            "The following prior knowledge from previous analyses may be relevant. "
            "Use it to provide deeper insights if applicable:\n\n"
            + prior_knowledge
            + "\n"
        )
    else:
        prior_section = ""

    chunks = split_logs(log_text)
    logger.info("Split logs into %d chunk(s), using model '%s'", len(chunks), selected_model)

    combined_analysis = []

    for i, chunk in enumerate(chunks, 1):
        logger.info("Analyzing chunk %d/%d …", i, len(chunks))
        formatted_prompt = log_analysis_prompt_text.format(
            log_data=chunk,
            prior_knowledge=prior_section,
        )
        result = await llm.ainvoke(formatted_prompt)
        combined_analysis.append(result.content)

    full_analysis = "\n\n---\n\n".join(combined_analysis)

    return full_analysis, context_used


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main HTML page."""
    html_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


@app.post("/analyze")
async def analyze_log_file(
    file: UploadFile = File(...),
    model: str | None = None,
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

        insights, context_used = await analyze_logs(log_text, model)

        # Extract entities from analysis and add to knowledge graph
        kg_update = {}
        try:
            kg_update = await kg_manager.add_analysis_entities(
                analysis_text=insights,
                filename=filename,
                model=model,
            )
        except Exception as kg_err:
            logger.warning("Knowledge graph update failed (non-fatal): %s", kg_err)

        return {
            "analysis": insights,
            "knowledge_graph": {
                "context_used": context_used,
                "update": kg_update,
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

        return {"models": models, "default": DEFAULT_MODEL}

    except Exception as e:
        logger.warning("Could not connect to Ollama: %s", e)
        return JSONResponse(
            status_code=503,
            content={"error": "Cannot connect to Ollama. Is it running?"},
        )


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

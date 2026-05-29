# Integrate Graphify Knowledge Graph into LogAnalyzer

## Background

LogAnalyzer currently processes uploaded log files in a stateless manner — each analysis is independent with no memory of past insights. The goal is to integrate **Graphify** (`graphifyy` on PyPI) to build a **persistent knowledge graph** from log analyses, enabling:

1. **Auto-build**: When a developer analyzes logs, the tool extracts entities (errors, services, patterns, root causes) and relationships, adding them to a persistent knowledge graph.
2. **Context-enriched analysis**: On subsequent analyses, the LLM receives relevant prior knowledge from the graph, producing richer, more contextual insights.
3. **Restructure on demand**: Developers can ask the tool to reconsider and restructure the entire knowledge graph.
4. **Developer insights**: Developers can manually add insights/notes that get woven into the knowledge graph.

## User Review Required

> [!IMPORTANT]
> **Graphify is primarily a CLI tool** designed for static code analysis via `tree-sitter`. Our use case is different — we're building a **dynamic knowledge graph from log analysis results** rather than from source code. The plan uses Graphify's **underlying graph format** (NetworkX `node_link_data` JSON) and its **MCP serve capability** for querying, but the graph population will be done by our own LLM-driven extraction pipeline. This is a custom integration, not a standard `graphify .` scan.

> [!WARNING]
> **New dependency**: `graphifyy` will be added to `requirements.txt`. It pulls in `networkx`, `tree-sitter`, and several other dependencies. The `networkx` portion is what we primarily use. If you'd prefer a lighter approach using only `networkx` directly (without `graphifyy`), let me know.

## Open Questions

1. **Storage location**: The plan stores the knowledge graph at `./knowledge_graph/graph.json`. Should this be configurable via `.env`?
2. **Graph scope**: Should there be one global graph, or per-project/per-file graphs? The current plan uses a single global graph.
3. **Graphify MCP server**: Should we also start the Graphify MCP server (`python -m graphify.serve`) for external tool access, or keep everything internal to our FastAPI app?

---

## Proposed Changes

### Knowledge Graph Module (New)

#### [NEW] [knowledge_graph.py](file:///d:/LogAnalyzer/knowledge_graph.py)

A new module that manages the persistent knowledge graph. Key responsibilities:

- **`KnowledgeGraphManager` class**:
  - `load()` / `save()` — Persist graph as NetworkX `node_link_data` JSON to `./knowledge_graph/graph.json`
  - `add_analysis_entities(analysis_text, filename, timestamp)` — Uses the LLM to extract structured entities (services, errors, root causes, patterns) and relationships from an analysis result, then merges them into the graph
  - `get_relevant_context(log_text)` — Given new log text, queries the graph for related nodes (matching service names, error types, etc.) and returns a markdown summary of prior knowledge
  - `restructure(instructions)` — Sends the entire graph + instructions to the LLM to produce a restructured version (merge duplicates, re-categorize, update relationships)
  - `add_developer_insight(insight_text, related_entities)` — Adds a developer-provided insight node linked to specified entities
  - `get_graph_summary()` — Returns stats + top entities for the UI
  - `get_graph_data()` — Returns the full graph in a format suitable for visualization (nodes + edges with metadata)
  - `clear()` — Resets the graph

**Entity types** extracted from analyses:
| Node Type | Examples |
|-----------|---------|
| `service` | "auth-service", "database", "nginx" |
| `error` | "ConnectionTimeout", "NullPointerException" |
| `root_cause` | "connection pool exhaustion", "memory leak" |
| `pattern` | "cascading failure", "retry storm" |
| `fix` | "increase pool size", "add circuit breaker" |
| `insight` | Developer-provided notes |

**Edge types**: `caused_by`, `relates_to`, `fixed_by`, `observed_in`, `depends_on`

---

### Backend API Changes

#### [MODIFY] [app.py](file:///d:/LogAnalyzer/app.py)

1. **Import & initialize** `KnowledgeGraphManager`
2. **Modify `analyze_logs()`**: After LLM analysis completes, extract entities and add to graph. Before analysis, query graph for relevant context and inject it into the prompt.
3. **New endpoints**:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/knowledge-graph` | Get graph summary + stats |
| GET | `/knowledge-graph/data` | Get full graph data for visualization |
| POST | `/knowledge-graph/restructure` | Trigger graph restructure with optional instructions |
| POST | `/knowledge-graph/insight` | Add a developer insight |
| DELETE | `/knowledge-graph` | Clear the graph |

4. **Modified prompt**: The SRE prompt will be augmented with a "Prior Knowledge" section when relevant context exists in the graph.

---

### Frontend UI Changes

#### [MODIFY] [index.html](file:///d:/LogAnalyzer/index.html)

Add a new **Knowledge Graph** section below the results card:

1. **Knowledge Graph Panel** (collapsible card):
   - **Graph Stats Bar**: Node count, edge count, last updated timestamp
   - **Interactive Visualization**: A force-directed graph rendered with `d3.js` (loaded from CDN) showing entities and relationships with color-coded node types
   - **Controls**:
     - 🔄 **Restructure** button — opens a modal where the developer can provide instructions (or leave blank for auto-restructure)
     - 💡 **Add Insight** button — opens a modal with a text area for the insight and optional entity tags
     - 🗑️ **Clear Graph** button — with confirmation dialog
   - **Context indicator** on the analysis results showing "Enhanced with N prior insights" when the graph contributed context

2. **Styling**: 
   - Graph visualization in a dark-themed canvas matching the existing glassmorphism design
   - Color-coded nodes: services (blue), errors (red), root causes (orange), patterns (purple), fixes (green), insights (yellow)
   - Animated edges, hover tooltips with node details
   - Smooth transitions when graph updates

---

### Dependencies

#### [MODIFY] [requirements.txt](file:///d:/LogAnalyzer/requirements.txt)

Add:
```
graphifyy>=0.8.0
networkx>=3.0
```

---

### Configuration

#### [MODIFY] [.env.example](file:///d:/LogAnalyzer/.env.example)

Add:
```env
# Knowledge graph storage directory
# KNOWLEDGE_GRAPH_DIR=./knowledge_graph
```

---

### Data Storage

#### [NEW] knowledge_graph/ (directory)

Created at runtime. Contains:
- `graph.json` — The persistent NetworkX graph
- `backups/` — Timestamped backups before restructures

---

## Verification Plan

### Automated Tests

1. **Unit test the `KnowledgeGraphManager`**:
   ```bash
   python -c "from knowledge_graph import KnowledgeGraphManager; mgr = KnowledgeGraphManager(); print(mgr.get_graph_summary())"
   ```

2. **API endpoint tests**:
   ```bash
   # Test graph summary
   curl http://localhost:8000/knowledge-graph
   
   # Test adding insight
   curl -X POST http://localhost:8000/knowledge-graph/insight \
     -H "Content-Type: application/json" \
     -d '{"insight": "Database connections spike every Monday at 9 AM"}'
   
   # Test restructure
   curl -X POST http://localhost:8000/knowledge-graph/restructure \
     -H "Content-Type: application/json" \
     -d '{"instructions": "Merge duplicate error nodes"}'
   ```

3. **End-to-end flow**:
   - Upload `sample_log.txt` → verify analysis includes graph extraction
   - Upload again → verify "Prior Knowledge" appears in analysis
   - Check `/knowledge-graph/data` returns valid visualization data

### Manual Verification

- Verify the D3.js graph renders correctly in the browser
- Verify the restructure and insight modals work
- Verify graph persists across server restarts

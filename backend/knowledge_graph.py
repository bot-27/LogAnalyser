"""
Knowledge Graph Manager for LogAnalyzer
=========================================
Builds and maintains a persistent knowledge graph from log analysis results.
Uses NetworkX for graph operations and persists in Graphify-compatible
node_link_data JSON format.

Entity types: service, error, root_cause, pattern, fix, insight
Edge types:   caused_by, relates_to, fixed_by, observed_in, depends_on
"""

import json
import logging
import os
import shutil
import re
from datetime import datetime, timezone
from typing import Optional

import networkx as nx
from langchain_ollama import ChatOllama

logger = logging.getLogger("loganalyzer.knowledgegraph")

# ---------------------------------------------------------------------------
# Extraction prompt — asks LLM to pull structured entities from analysis text
# ---------------------------------------------------------------------------
ENTITY_EXTRACTION_PROMPT = """\
You are a knowledge-graph extraction engine.

Given the following log analysis text, extract entities and relationships.

**Entity types** (use exactly these labels):
- service     — any application, microservice, database, or infrastructure component mentioned
- event       — significant system events (e.g., startup, shutdown, state change)
- transaction — business or technical workflows (e.g., payment, login)
- config      — configuration states or environment settings
- error       — specific error types, exceptions, or failure modes
- root_cause   — underlying causes identified in the analysis
- pattern     — recurring patterns or trends (e.g., "retry storm", "cascading failure")
- fix         — suggested fixes or remediation steps

**Relationship types** (use exactly these labels):
- caused_by      — entity A was caused by entity B
- relates_to     — entity A is related to entity B
- fixed_by       — entity A can be fixed by entity B
- observed_in    — entity A was observed in entity B (e.g., error observed in service)
- depends_on     — entity A depends on entity B
- calls          — entity A calls entity B
- transitions_to — entity A transitions to entity B
- configured_with— entity A is configured with entity B

**Developer Insights:**
Consider the following developer insights to guide your extraction priority:
{developer_insights}

Return ONLY valid JSON in this exact format (no markdown, no extra text):
{{
  "entities": [
    {{"id": "unique_snake_case_id", "type": "service|event|transaction|config|error|root_cause|pattern|fix", "label": "Human Readable Name", "description": "Brief description"}}
  ],
  "relationships": [
    {{"source": "entity_id_1", "target": "entity_id_2", "type": "caused_by|relates_to|fixed_by|observed_in|depends_on|calls|transitions_to|configured_with"}}
  ]
}}

Analysis text:
{analysis_text}

Source file: {filename}
"""

RESTRUCTURE_PROMPT = """\
You are a knowledge-graph restructuring engine.

Below is the current knowledge graph in JSON format. Restructure it according to the instructions.

**Tasks to perform:**
1. Merge duplicate or near-duplicate entities (same concept, different wording)
2. Remove weak or irrelevant relationships
3. Strengthen entity descriptions based on accumulated evidence
4. Re-categorize entities if their type is wrong
5. Prune low-value generic event nodes if they don't connect to important transactions or errors
6. Apply any additional instructions from the developer

**Developer instructions:**
{instructions}

**Current graph nodes:**
{nodes_json}

**Current graph edges:**
{edges_json}

Return ONLY valid JSON in this exact format (no markdown, no extra text):
{{
  "entities": [
    {{"id": "unique_snake_case_id", "type": "service|event|transaction|config|error|root_cause|pattern|fix|insight", "label": "Human Readable Name", "description": "Brief description", "observation_count": 1}}
  ],
  "relationships": [
    {{"source": "entity_id_1", "target": "entity_id_2", "type": "caused_by|relates_to|fixed_by|observed_in|depends_on|calls|transitions_to|configured_with"}}
  ]
}}
"""


class KnowledgeGraphManager:
    """Manages a persistent knowledge graph built from log analyses."""

    def __init__(
        self,
        storage_dir: str = "./knowledge_graph",
        ollama_base_url: str = "http://localhost:11434",
        default_model: str = "llama3.1:8b",
    ):
        self.storage_dir = storage_dir
        self.graph_path = os.path.join(storage_dir, "graph.json")
        self.backups_dir = os.path.join(storage_dir, "backups")
        self.ollama_base_url = ollama_base_url
        self.default_model = default_model
        self.graph: nx.DiGraph = nx.DiGraph()
        self._ensure_dirs()
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _ensure_dirs(self):
        """Create storage directories if they don't exist."""
        os.makedirs(self.storage_dir, exist_ok=True)
        os.makedirs(self.backups_dir, exist_ok=True)

    def load(self):
        """Load the graph from disk, or start fresh."""
        if os.path.exists(self.graph_path):
            try:
                with open(self.graph_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.graph = nx.node_link_graph(data, directed=True)
                logger.info(
                    "Loaded knowledge graph: %d nodes, %d edges",
                    self.graph.number_of_nodes(),
                    self.graph.number_of_edges(),
                )
            except Exception as e:
                logger.warning("Failed to load graph, starting fresh: %s", e)
                self.graph = nx.DiGraph()
        else:
            self.graph = nx.DiGraph()
            logger.info("No existing graph found — starting fresh")

    def save(self):
        """Persist the graph to disk in node_link_data format."""
        self._ensure_dirs()
        data = nx.node_link_data(self.graph)
        with open(self.graph_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(
            "Saved knowledge graph: %d nodes, %d edges",
            self.graph.number_of_nodes(),
            self.graph.number_of_edges(),
        )

    def _backup(self):
        """Create a timestamped backup before destructive operations."""
        if os.path.exists(self.graph_path):
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            dest = os.path.join(self.backups_dir, f"graph_{ts}.json")
            shutil.copy2(self.graph_path, dest)
            logger.info("Backed up graph to %s", dest)

    # ------------------------------------------------------------------
    # LLM helper
    # ------------------------------------------------------------------
    def _get_llm(self, model: Optional[str] = None) -> ChatOllama:
        return ChatOllama(
            model=model or self.default_model,
            temperature=0.1,
            base_url=self.ollama_base_url,
        )

    async def _extract_json_from_llm(self, prompt: str, model: Optional[str] = None) -> dict:
        """Send a prompt to the LLM and parse the JSON response."""
        llm = self._get_llm(model)
        result = await llm.ainvoke(prompt)
        text = result.content.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last fence lines
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning("LLM returned invalid JSON: %s\nRaw: %s", e, text[:500])
            return {"entities": [], "relationships": []}

    # ------------------------------------------------------------------
    # Pass 1: Deterministic Entity extraction
    # ------------------------------------------------------------------
    def add_deterministic_entities(self, raw_log_text: str, filename: str) -> dict:
        """
        Pass 1: Deterministic extraction of structured data from raw logs using regex.
        Extracts IPs and log levels and creates 100% confidence nodes and edges.
        """
        now = datetime.now(timezone.utc).isoformat()
        added_nodes = 0
        added_edges = 0

        # Patterns
        ip_pattern = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')
        level_pattern = re.compile(r'\b(ERROR|WARN|WARNING|INFO|DEBUG|FATAL|CRITICAL)\b', re.IGNORECASE)

        lines = raw_log_text.splitlines()
        for line in lines:
            ips = ip_pattern.findall(line)
            levels = level_pattern.findall(line)

            for ip in ips:
                eid = f"ip_{ip.replace('.', '_')}"
                if not self.graph.has_node(eid):
                    self.graph.add_node(
                        eid, type="config", label=ip, description=f"IP Address {ip}",
                        observation_count=1, first_seen=now, last_seen=now, sources=[filename],
                        provenance="Extracted"
                    )
                    added_nodes += 1
                else:
                    attrs = self.graph.nodes[eid]
                    attrs["observation_count"] = attrs.get("observation_count", 1) + 1
                    attrs["last_seen"] = now
                    if filename not in attrs.get("sources", []):
                        attrs.setdefault("sources", []).append(filename)

                for lvl in levels:
                    lvl_upper = lvl.upper()
                    lvl_eid = f"level_{lvl_upper.lower()}"
                    if not self.graph.has_node(lvl_eid):
                        self.graph.add_node(
                            lvl_eid, type="event", label=f"Level: {lvl_upper}", description=f"Log Level {lvl_upper}",
                            observation_count=1, first_seen=now, last_seen=now, sources=[filename],
                            provenance="Extracted"
                        )
                        added_nodes += 1
                    else:
                        self.graph.nodes[lvl_eid]["observation_count"] = self.graph.nodes[lvl_eid].get("observation_count", 1) + 1

                    if not self.graph.has_edge(eid, lvl_eid):
                        self.graph.add_edge(eid, lvl_eid, type="observed_in", created=now, provenance="Extracted")
                        added_edges += 1

        if added_nodes > 0 or added_edges > 0:
            self.save()

        summary = {"added_nodes": added_nodes, "added_edges": added_edges}
        logger.info("Deterministic graph update from '%s': %s", filename, summary)
        return summary

    # ------------------------------------------------------------------
    # Pass 3: Semantic Entity extraction (called after each analysis)
    # ------------------------------------------------------------------
    async def add_analysis_entities(
        self,
        analysis_text: str,
        filename: str,
        model: Optional[str] = None,
    ) -> dict:
        """
        Extract entities from an analysis result and merge into the graph.
        Returns summary of what was added.
        """
        # Gather developer insights from the graph
        insights = []
        for nid, attrs in self.graph.nodes(data=True):
            if attrs.get("type") == "insight":
                insights.append(attrs.get("description", ""))
        insights_text = "\\n".join(f"- {txt}" for txt in insights) if insights else "No specific developer insights available."

        prompt = ENTITY_EXTRACTION_PROMPT.format(
            analysis_text=analysis_text,
            filename=filename,
            developer_insights=insights_text,
        )

        data = await self._extract_json_from_llm(prompt, model)
        entities = data.get("entities", [])
        relationships = data.get("relationships", [])
        now = datetime.now(timezone.utc).isoformat()

        added_nodes = 0
        updated_nodes = 0
        added_edges = 0

        for entity in entities:
            eid = entity.get("id", "").strip()
            if not eid:
                continue

            if self.graph.has_node(eid):
                # Bump observation count and update metadata
                attrs = self.graph.nodes[eid]
                attrs["observation_count"] = attrs.get("observation_count", 1) + 1
                attrs["last_seen"] = now
                sources = attrs.get("sources", [])
                if filename not in sources:
                    sources.append(filename)
                    attrs["sources"] = sources
                updated_nodes += 1
            else:
                self.graph.add_node(
                    eid,
                    type=entity.get("type", "unknown"),
                    label=entity.get("label", eid),
                    description=entity.get("description", ""),
                    observation_count=1,
                    first_seen=now,
                    last_seen=now,
                    sources=[filename],
                    provenance="Inferred",
                )
                added_nodes += 1

        for rel in relationships:
            src = rel.get("source", "").strip()
            tgt = rel.get("target", "").strip()
            rtype = rel.get("type", "relates_to")
            if src and tgt and self.graph.has_node(src) and self.graph.has_node(tgt):
                if not self.graph.has_edge(src, tgt):
                    self.graph.add_edge(src, tgt, type=rtype, created=now, provenance="Inferred")
                    added_edges += 1

        self.save()

        summary = {
            "added_nodes": added_nodes,
            "updated_nodes": updated_nodes,
            "added_edges": added_edges,
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
        }
        logger.info("Graph update from '%s': %s", filename, summary)
        return summary

    # ------------------------------------------------------------------
    # Context retrieval (called before each analysis)
    # ------------------------------------------------------------------
    def get_relevant_context(self, log_text: str, max_nodes: int = 15) -> str:
        """
        Search the graph for nodes related to the incoming log text.
        Returns a markdown summary of prior knowledge.
        """
        if self.graph.number_of_nodes() == 0:
            return ""

        log_lower = log_text.lower()
        scored_nodes = []

        for node_id, attrs in self.graph.nodes(data=True):
            score = 0
            label = attrs.get("label", "").lower()
            desc = attrs.get("description", "").lower()

            # Score by keyword presence in the log text
            for word in label.split():
                if len(word) > 2 and word in log_lower:
                    score += 3
            for word in desc.split():
                if len(word) > 3 and word in log_lower:
                    score += 1

            # Boost by observation count (more established = more relevant)
            score += min(attrs.get("observation_count", 1) - 1, 5)

            # Heavily boost developer insights so they are always prioritized
            if attrs.get("type") == "insight":
                score += 10

            if score > 0:
                scored_nodes.append((node_id, attrs, score))

        if not scored_nodes:
            return ""

        # Sort by relevance score, take top N
        scored_nodes.sort(key=lambda x: x[2], reverse=True)
        top_nodes = scored_nodes[:max_nodes]

        lines = [
            "## Prior Knowledge from Knowledge Graph",
            f"*{len(top_nodes)} relevant entities found from previous analyses:*\n",
        ]

        for node_id, attrs, _score in top_nodes:
            ntype = attrs.get("type", "unknown")
            label = attrs.get("label", node_id)
            desc = attrs.get("description", "")
            count = attrs.get("observation_count", 1)
            icon = {
                "service": "🔧",
                "error": "❌",
                "root_cause": "🔍",
                "pattern": "🔄",
                "fix": "✅",
                "insight": "💡",
            }.get(ntype, "📌")

            lines.append(f"- {icon} **{label}** ({ntype}, seen {count}x): {desc}")

            # Include connected entities
            neighbors = list(self.graph.successors(node_id))[:3]
            for nbr in neighbors:
                edge_data = self.graph.edges[node_id, nbr]
                nbr_label = self.graph.nodes[nbr].get("label", nbr)
                rel_type = edge_data.get("type", "relates_to")
                lines.append(f"  → *{rel_type}* → {nbr_label}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Restructure
    # ------------------------------------------------------------------
    async def restructure(
        self,
        instructions: str = "Auto-restructure: merge duplicates and clean up.",
        model: Optional[str] = None,
    ) -> dict:
        """
        Send the entire graph to the LLM for restructuring.
        Creates a backup first.
        """
        self._backup()

        if self.graph.number_of_nodes() == 0:
            return {"status": "empty", "message": "Graph is empty, nothing to restructure"}

        # Serialize current graph for the prompt
        nodes_list = []
        for nid, attrs in self.graph.nodes(data=True):
            nodes_list.append({
                "id": nid,
                "type": attrs.get("type", "unknown"),
                "label": attrs.get("label", nid),
                "description": attrs.get("description", ""),
                "observation_count": attrs.get("observation_count", 1),
            })

        edges_list = []
        for src, tgt, attrs in self.graph.edges(data=True):
            edges_list.append({
                "source": src,
                "target": tgt,
                "type": attrs.get("type", "relates_to"),
            })

        prompt = RESTRUCTURE_PROMPT.format(
            instructions=instructions,
            nodes_json=json.dumps(nodes_list, indent=2),
            edges_json=json.dumps(edges_list, indent=2),
        )

        data = await self._extract_json_from_llm(prompt, model)

        # Rebuild graph from LLM response
        old_count = (self.graph.number_of_nodes(), self.graph.number_of_edges())
        self.graph = nx.DiGraph()
        now = datetime.now(timezone.utc).isoformat()

        for entity in data.get("entities", []):
            eid = entity.get("id", "").strip()
            if eid:
                self.graph.add_node(
                    eid,
                    type=entity.get("type", "unknown"),
                    label=entity.get("label", eid),
                    description=entity.get("description", ""),
                    observation_count=entity.get("observation_count", 1),
                    restructured_at=now,
                )

        for rel in data.get("relationships", []):
            src = rel.get("source", "").strip()
            tgt = rel.get("target", "").strip()
            if src and tgt and self.graph.has_node(src) and self.graph.has_node(tgt):
                self.graph.add_edge(src, tgt, type=rel.get("type", "relates_to"), created=now)

        self.save()
        new_count = (self.graph.number_of_nodes(), self.graph.number_of_edges())

        result = {
            "status": "restructured",
            "before": {"nodes": old_count[0], "edges": old_count[1]},
            "after": {"nodes": new_count[0], "edges": new_count[1]},
        }
        logger.info("Graph restructured: %s", result)
        return result

    # ------------------------------------------------------------------
    # Developer insights
    # ------------------------------------------------------------------
    async def add_developer_insight(
        self,
        insight_text: str,
        related_entities: Optional[list[str]] = None,
    ) -> dict:
        """Add a developer-provided insight as a node in the graph."""
        now = datetime.now(timezone.utc)
        insight_id = f"insight_{now.strftime('%Y%m%d_%H%M%S')}"

        self.graph.add_node(
            insight_id,
            type="insight",
            label=insight_text[:80],
            description=insight_text,
            observation_count=1,
            first_seen=now.isoformat(),
            last_seen=now.isoformat(),
            sources=["developer"],
            provenance="Developer_Insight",
        )

        linked = 0
        if related_entities:
            for entity_id in related_entities:
                if self.graph.has_node(entity_id):
                    self.graph.add_edge(
                        insight_id,
                        entity_id,
                        type="relates_to",
                        created=now.isoformat(),
                    )
                    linked += 1

        self.save()
        return {
            "insight_id": insight_id,
            "linked_to": linked,
            "total_nodes": self.graph.number_of_nodes(),
        }

    # ------------------------------------------------------------------
    # Graph data for API / visualization
    # ------------------------------------------------------------------
    def get_graph_summary(self) -> dict:
        """Return high-level graph statistics."""
        type_counts: dict[str, int] = {}
        for _, attrs in self.graph.nodes(data=True):
            ntype = attrs.get("type", "unknown")
            type_counts[ntype] = type_counts.get(ntype, 0) + 1

        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "entity_types": type_counts,
            "has_data": self.graph.number_of_nodes() > 0,
        }

    def get_graph_data(self) -> dict:
        """Return full graph in visualization-friendly format."""
        nodes = []
        for nid, attrs in self.graph.nodes(data=True):
            nodes.append({
                "id": nid,
                "type": attrs.get("type", "unknown"),
                "label": attrs.get("label", nid),
                "description": attrs.get("description", ""),
                "observation_count": attrs.get("observation_count", 1),
                "first_seen": attrs.get("first_seen", ""),
                "last_seen": attrs.get("last_seen", ""),
            })

        edges = []
        for src, tgt, attrs in self.graph.edges(data=True):
            edges.append({
                "source": src,
                "target": tgt,
                "type": attrs.get("type", "relates_to"),
            })

        return {"nodes": nodes, "edges": edges}

    def clear(self) -> dict:
        """Clear the entire graph (with backup)."""
        self._backup()
        old_count = self.graph.number_of_nodes()
        self.graph = nx.DiGraph()
        self.save()
        logger.info("Graph cleared (had %d nodes)", old_count)
        return {"cleared_nodes": old_count, "status": "cleared"}

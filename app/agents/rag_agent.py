"""RAG agent for indexing lead research into ChromaDB and retrieving grounded context."""
from __future__ import annotations

import logging
from typing import Any

from app.rag.retriever import retrieve_context, retrieve_context_for_lead
from app.rag.vector_store import index_lead_research

logger = logging.getLogger(__name__)


def rag_agent(
    query: str,
    *,
    lead_id: str | None = None,
    k: int = 3,
) -> list[dict[str, Any]]:
    """Retrieve grounded documents for a query, optionally filtering by lead_id.

    Returns a list of dicts with content, source, and metadata.
    """
    query = query.strip() if isinstance(query, str) else ""
    if not query:
        raise ValueError("A retrieval query is required.")
    if not 1 <= k <= 8:
        raise ValueError("k must be between 1 and 8.")

    if lead_id:
        docs = retrieve_context_for_lead(lead_id=lead_id, query=query, k=k)
    else:
        docs = retrieve_context(query=query, k=k)

    return [
        {
            "content": doc.page_content,
            "source": str(doc.metadata.get("source", "unknown")),
            "metadata": doc.metadata,
        }
        for doc in docs
    ]


def index_lead_knowledge(
    lead_id: str,
    business_name: str,
    research: dict[str, Any],
    website_pages: list[dict[str, Any]] | None = None,
) -> int:
    """Index research findings and scraped website content into ChromaDB."""
    return index_lead_research(
        lead_id=lead_id,
        business_name=business_name,
        research=research,
        website_pages=website_pages,
    )

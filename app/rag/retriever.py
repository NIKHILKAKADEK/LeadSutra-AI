"""Retriever interface for knowledge base and lead-specific contexts."""
from __future__ import annotations

from langchain_core.documents import Document

from app.rag.vector_store import (
    retrieve_context as _retrieve_context,
    retrieve_context_for_lead as _retrieve_context_for_lead,
)


def retrieve_context(query: str, k: int = 2) -> list[Document]:
    """Retrieve general knowledge documents for a query."""
    return _retrieve_context(query=query, k=k)


def retrieve_context_for_lead(lead_id: str, query: str, k: int = 4) -> list[Document]:
    """Retrieve grounded documents filtered specifically for a selected lead."""
    return _retrieve_context_for_lead(lead_id=lead_id, query=query, k=k)
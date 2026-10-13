"""Vector store management, knowledge base seeding, and lead-specific RAG indexing."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.embeddings import embeddings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "leadsutra_knowledge"
RAG_DIRECTORY = Path(__file__).resolve().parents[2] / "data" / "rag"
PERSIST_DIRECTORY = str(RAG_DIRECTORY / "chroma")

DOCUMENT_IDS = [
    "website_services",
    "digital_marketing",
    "sales_proposals",
    "lead_generation_crm",
    "social_media_delivery",
]

_text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=600,
    chunk_overlap=80,
    separators=["\n\n", "\n", ". ", " ", ""],
)


def _load_static_documents() -> list[tuple[str, Document]]:
    docs = []
    for doc_id in DOCUMENT_IDS:
        doc_path = RAG_DIRECTORY / f"{doc_id}.txt"
        if doc_path.is_file():
            try:
                content = doc_path.read_text(encoding="utf-8")
                docs.append((doc_id, Document(page_content=content, metadata={"source": doc_id, "type": "knowledge_base"})))
            except Exception as exc:
                logger.warning("Could not read knowledge file %s: %s", doc_path, exc)
    return docs


try:
    vector_store = Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=PERSIST_DIRECTORY,
    )
except Exception as exc:
    logger.error("Failed to initialize Chroma vector store: %s", exc)
    vector_store = None


def seed_knowledge_base() -> int:
    """Insert stable knowledge base documents if not already persisted."""
    if vector_store is None:
        return 0
    static_docs = _load_static_documents()
    if not static_docs:
        return 0
    try:
        existing_ids = set(vector_store._collection.get(ids=[doc_id for doc_id, _ in static_docs]).get("ids", []))
    except Exception as exc:
        logger.warning("Could not check existing Chroma IDs: %s", exc)
        existing_ids = set()

    missing = [(doc_id, doc) for doc_id, doc in static_docs if doc_id not in existing_ids]
    if missing:
        try:
            vector_store.add_documents(
                documents=[doc for _, doc in missing],
                ids=[doc_id for doc_id, _ in missing],
            )
            logger.info("Added %d static documents to knowledge base.", len(missing))
        except Exception as exc:
            logger.error("Failed to seed knowledge base: %s", exc)
            return 0
    return len(missing)


def index_lead_research(
    lead_id: str,
    business_name: str,
    research: dict[str, Any],
    website_pages: list[dict[str, Any]] | None = None,
) -> int:
    """Convert research results and website text into chunks and index into Chroma with lead metadata.

    Ensures that each chunk is tagged with lead_id so that future proposal generation
    can retrieve strictly grounded facts isolated to this prospect.
    """
    if vector_store is None:
        raise RuntimeError("Vector store is unavailable.")
    if not lead_id:
        raise ValueError("A valid lead_id is required for indexing.")

    now_iso = datetime.now(timezone.utc).isoformat()
    raw_docs: list[Document] = []

    # 1. Structured research sections
    summary = research.get("business_summary")
    if summary and isinstance(summary, str) and summary.strip():
        raw_docs.append(Document(
            page_content=f"Business Summary for {business_name}:\n{summary.strip()}",
            metadata={"source": "research_summary", "document_type": "summary", "lead_id": lead_id, "business_name": business_name, "timestamp": now_iso},
        ))

    services = research.get("products_services") or research.get("services")
    if services and isinstance(services, list):
        clean_services = [s for s in services if isinstance(s, str) and s.strip()]
        if clean_services:
            raw_docs.append(Document(
                page_content=f"Products and Services offered by {business_name}:\n" + "\n- ".join(clean_services),
                metadata={"source": "research_services", "document_type": "services", "lead_id": lead_id, "business_name": business_name, "timestamp": now_iso},
            ))

    swot = research.get("swot")
    if isinstance(swot, dict):
        swot_lines = []
        for key in ("strengths", "weaknesses", "opportunities", "threats"):
            items = swot.get(key)
            if items and isinstance(items, list):
                valid = [i for i in items if isinstance(i, str) and i.strip() and "not enough information" not in i.lower()]
                if valid:
                    swot_lines.append(f"{key.capitalize()}:\n- " + "\n- ".join(valid))
        if swot_lines:
            raw_docs.append(Document(
                page_content=f"SWOT Analysis for {business_name}:\n" + "\n\n".join(swot_lines),
                metadata={"source": "research_swot", "document_type": "swot", "lead_id": lead_id, "business_name": business_name, "timestamp": now_iso},
            ))

    facts = research.get("provided_facts") or research.get("evidence")
    if facts and isinstance(facts, list):
        clean_facts = [f for f in facts if isinstance(f, str) and f.strip()]
        if clean_facts:
            raw_docs.append(Document(
                page_content=f"Verified Facts for {business_name}:\n" + "\n- ".join(clean_facts),
                metadata={"source": "research_facts", "document_type": "facts", "lead_id": lead_id, "business_name": business_name, "timestamp": now_iso},
            ))

    opportunities = research.get("sales_opportunities") or research.get("opportunities")
    if opportunities and isinstance(opportunities, list):
        clean_opps = [o for o in opportunities if isinstance(o, str) and o.strip() and "not enough information" not in o.lower()]
        if clean_opps:
            raw_docs.append(Document(
                page_content=f"Identified Sales Opportunities for {business_name}:\n" + "\n- ".join(clean_opps),
                metadata={"source": "research_opportunities", "document_type": "opportunities", "lead_id": lead_id, "business_name": business_name, "timestamp": now_iso},
            ))

    # 2. Website pages if available
    if website_pages:
        for page in website_pages:
            text = page.get("main_text") or page.get("text") or ""
            page_url = page.get("page_url") or page.get("url") or "website"
            page_type = page.get("page_type") or "page"
            if text and len(text.strip()) > 40:
                raw_docs.append(Document(
                    page_content=f"Website content from {page_url} ({page_type}):\n{text.strip()}",
                    metadata={"source": str(page_url), "document_type": f"website_{page_type}", "lead_id": lead_id, "business_name": business_name, "timestamp": now_iso},
                ))

    if not raw_docs:
        logger.info("No text documents to index for lead %s.", lead_id)
        return 0

    chunked_docs = _text_splitter.split_documents(raw_docs)
    doc_ids = []
    for idx, doc in enumerate(chunked_docs):
        content_hash = hashlib.sha256(doc.page_content.encode("utf-8")).hexdigest()[:12]
        doc_ids.append(f"lead_{lead_id}_{idx}_{content_hash}")

    try:
        vector_store.add_documents(documents=chunked_docs, ids=doc_ids)
        logger.info("Indexed %d chunks for lead %s in ChromaDB.", len(chunked_docs), lead_id)
        return len(chunked_docs)
    except Exception as exc:
        logger.exception("Failed to add documents to Chroma for lead %s: %s", lead_id, exc)
        raise RuntimeError(f"Chroma indexing failed for lead {lead_id}: {exc}") from exc


def retrieve_context_for_lead(
    lead_id: str,
    query: str,
    k: int = 4,
) -> list[Document]:
    """Retrieve grounded knowledge chunks filtered strictly by lead_id, plus sales guidelines."""
    if vector_store is None:
        raise RuntimeError("Vector store is unavailable.")
    if not query or not query.strip():
        return []

    # 1. Retrieve lead-specific documents
    lead_results: list[Document] = []
    if lead_id:
        try:
            lead_results = vector_store.similarity_search(
                query=query,
                k=k,
                filter={"lead_id": lead_id},
            )
        except Exception as exc:
            logger.warning("Lead-specific retrieval failed for lead %s: %s", lead_id, exc)

    # 2. Retrieve sales methodology knowledge base docs
    general_results: list[Document] = []
    try:
        general_results = vector_store.similarity_search(
            query=query,
            k=max(2, k // 2),
            filter={"type": "knowledge_base"},
        )
    except Exception:
        pass

    combined = lead_results + [d for d in general_results if d not in lead_results]
    return combined[:k]


def retrieve_context(query: str, k: int = 2) -> list[Document]:
    """Legacy/general similarity search for knowledge documents."""
    if vector_store is None:
        raise RuntimeError("Vector store is unavailable.")
    return vector_store.similarity_search(query, k=k)

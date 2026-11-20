"""MongoDB connection shared by backend persistence services."""
from __future__ import annotations

import logging
from functools import lru_cache
from threading import Lock
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)
_connection_lock = Lock()


class MongoDatabase:
    """Lazy synchronous PyMongo connection used by the existing sync service APIs."""

    def __init__(self, uri: str, database_name: str, timeout_ms: int) -> None:
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise RuntimeError(
                "MongoDB is configured but PyMongo is not installed. "
                "Install the dependencies in requirements.txt."
            ) from exc

        self._client = MongoClient(
            uri,
            serverSelectionTimeoutMS=timeout_ms,
            appname="LeadSutraAI",
        )
        self.database = self._client[database_name]
        self.connected = False

    def connect(self) -> None:
        """Verify MongoDB availability; configured database failures are explicit."""
        try:
            self._client.admin.command("ping")
        except Exception:
            logger.exception("Could not connect to the configured MongoDB database")
            raise
        self.database["workflows"].create_index([("updated_at", -1)])
        self.database["leads"].create_index([("updated_at", -1)])
        self.database["lead_runs"].create_index([("created_at", -1)])
        self.database["users"].create_index("email", unique=True)
        self.database["email_results"].create_index(
            "review_id",
            unique=True,
            partialFilterExpression={"review_id": {"$type": "string"}},
        )
        self.database["email_results"].create_index([("created_at", -1)])
        self.database["email_drafts"].create_index([("created_at", -1)])
        self.database["call_dispatches"].create_index([("created_at", -1)])
        self.database["call_dispatches"].create_index([("lead_id", 1), ("status", 1)])
        self.database["follow_ups"].create_index("idempotency_key", unique=True)
        self.database["follow_ups"].create_index([("scheduled_at", 1), ("status", 1)])
        self.database["consents"].create_index(
            [("lead_id", 1), ("phone_number", 1)],
            unique=True,
        )
        self.database["proposals"].create_index([("updated_at", -1)])
        self.database["research"].create_index([("updated_at", -1)])
        self.connected = True
        logger.info("Connected to MongoDB database %s", self.database.name)

    def collection(self, name: str) -> Any:
        return self.database[name]

    def close(self) -> None:
        self._client.close()
        self.connected = False


@lru_cache(maxsize=1)
def get_mongo_database() -> MongoDatabase | None:
    """Return MongoDB when configured; application startup enforces this setting."""
    settings = get_settings()
    if (
        settings.mongodb_uri is None
        or not settings.mongodb_uri.get_secret_value().strip()
    ):
        return None
    with _connection_lock:
        return MongoDatabase(
            settings.mongodb_uri.get_secret_value(),
            settings.mongodb_database,
            settings.mongodb_server_selection_timeout_ms,
        )


def get_mongo_collection(name: str) -> Any | None:
    database = get_mongo_database()
    return database.collection(name) if database is not None else None


def close_mongo_database() -> None:
    """Close the shared client at application shutdown."""
    database = get_mongo_database()
    if database is not None:
        database.close()
    get_mongo_database.cache_clear()

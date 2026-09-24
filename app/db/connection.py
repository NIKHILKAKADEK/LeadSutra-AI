import logging
from typing import Any, Dict, List, Optional
from app.db.config import MongoConfig, default_mongo_config

logger = logging.getLogger(__name__)


class InMemoryAsyncCollection:
    """Mock async collection for testing and offline fallback."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.docs: Dict[str, Dict[str, Any]] = {}
        self.indexes: List[Dict[str, Any]] = []

    async def create_index(self, keys: Any, **kwargs: Any) -> str:
        idx_name = kwargs.get("name", str(keys))
        self.indexes.append({"keys": keys, "kwargs": kwargs, "name": idx_name})
        return idx_name

    async def insert_one(self, doc: Dict[str, Any]) -> Any:
        # Generate _id if missing
        doc_copy = dict(doc)
        _id = str(doc_copy.get("_id") or doc_copy.get("external_place_id") or doc_copy.get("lead_id") or f"doc_{len(self.docs)+1}")
        doc_copy["_id"] = _id
        self.docs[_id] = doc_copy

        class InsertResult:
            inserted_id = _id

        return InsertResult()

    async def find_one(self, filter_query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for doc in self.docs.values():
            match = True
            for k, v in filter_query.items():
                if k == "$or" and isinstance(v, list):
                    or_match = False
                    for cond in v:
                        if all(doc.get(sub_k) == sub_v for sub_k, sub_v in cond.items()):
                            or_match = True
                            break
                    if not or_match:
                        match = False
                        break
                elif doc.get(k) != v:
                    match = False
                    break
            if match:
                return dict(doc)
        return None

    async def find(self, filter_query: Dict[str, Any] = None, skip: int = 0, limit: int = 50) -> Any:
        filter_query = filter_query or {}
        matched = []
        for doc in self.docs.values():
            match = True
            for k, v in filter_query.items():
                if k == "lead_score" and isinstance(v, dict) and "$gte" in v:
                    if (doc.get("lead_score") or 0) < v["$gte"]:
                        match = False
                        break
                elif doc.get(k) != v:
                    match = False
                    break
            if match:
                matched.append(dict(doc))

        sliced = matched[skip : skip + limit]

        class AsyncCursor:
            def __init__(self, data: List[Dict[str, Any]]):
                self.data = data

            def __aiter__(self):
                self._iter = iter(self.data)
                return self

            async def __anext__(self):
                try:
                    return next(self._iter)
                except StopIteration:
                    raise StopAsyncIteration

            async def to_list(self, length: int = None):
                return self.data[:length] if length else self.data

        return AsyncCursor(sliced)

    async def update_one(self, filter_query: Dict[str, Any], update_doc: Dict[str, Any], upsert: bool = False) -> Any:
        existing = await self.find_one(filter_query)

        class UpdateResult:
            matched_count = 1 if existing else 0
            modified_count = 1 if existing else 0
            upserted_id = None

        if existing:
            _id = existing["_id"]
            target = self.docs[_id]

            if "$set" in update_doc:
                for k, v in update_doc["$set"].items():
                    if v is not None or k not in target:
                        target[k] = v

            if "$setOnInsert" in update_doc:
                pass  # Existing doc, ignore setOnInsert

            if "$addToSet" in update_doc:
                for k, v in update_doc["$addToSet"].items():
                    arr = target.get(k, [])
                    if not isinstance(arr, list):
                        arr = [arr]
                    if v not in arr:
                        arr.append(v)
                    target[k] = arr

            return UpdateResult()
        elif upsert:
            new_doc = {}
            for k, v in filter_query.items():
                if not k.startswith("$"):
                    new_doc[k] = v

            if "$set" in update_doc:
                for k, v in update_doc["$set"].items():
                    new_doc[k] = v

            if "$setOnInsert" in update_doc:
                for k, v in update_doc["$setOnInsert"].items():
                    new_doc[k] = v

            res = await self.insert_one(new_doc)
            UpdateResult.upserted_id = res.inserted_id
            return UpdateResult()

        return UpdateResult()


class MongoDatabase:
    """Async database connection manager with motor client and in-memory fallback."""

    def __init__(self, config: MongoConfig = default_mongo_config) -> None:
        self.config = config
        self._client = None
        self._db = None
        self._in_memory = False
        self._collections: Dict[str, Any] = {}

    async def connect(self) -> None:
        """Initializes connection to MongoDB or falls back to in-memory store."""
        try:
            import motor.motor_asyncio

            self._client = motor.motor_asyncio.AsyncIOMotorClient(
                self.config.uri,
                serverSelectionTimeoutMS=self.config.server_selection_timeout_ms,
            )
            # Ping database to verify connection
            await self._client.admin.command("ping")
            self._db = self._client[self.config.db_name]
            self._in_memory = False
            logger.info("Connected to MongoDB at %s (DB: %s)", self.config.uri, self.config.db_name)
        except Exception as exc:
            logger.warning(
                "MongoDB connection unavailable (%s). Falling back to in-memory database store for task execution.",
                str(exc),
            )
            self._in_memory = True

    def get_collection(self, collection_name: str) -> Any:
        """Returns collection instance for the specified name."""
        if self._in_memory or self._db is None:
            if collection_name not in self._collections:
                self._collections[collection_name] = InMemoryAsyncCollection(collection_name)
            return self._collections[collection_name]
        return self._db[collection_name]

    async def close(self) -> None:
        """Closes client connection."""
        if self._client and not self._in_memory:
            self._client.close()
            logger.info("Closed MongoDB connection.")


db_manager = MongoDatabase()

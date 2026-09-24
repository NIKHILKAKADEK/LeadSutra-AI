"""LeadSutra MongoDB Database configuration."""

import os
from dataclasses import dataclass


@dataclass
class MongoConfig:
    """MongoDB configuration settings loaded from environment variables."""

    uri: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    db_name: str = os.getenv("MONGODB_DB_NAME", "leadsutra")
    leads_collection: str = os.getenv("MONGODB_LEADS_COLLECTION", "leads")
    profiles_collection: str = os.getenv("MONGODB_PROFILES_COLLECTION", "business_profiles")
    server_selection_timeout_ms: int = int(os.getenv("MONGODB_TIMEOUT_MS", "3000"))


default_mongo_config = MongoConfig()

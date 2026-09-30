from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from app.db.config import MongoConfig, default_mongo_config
from app.db.connection import MongoDatabase, db_manager
from app.models.business_profile import BusinessProfile
from app.models.lead import BusinessLead

logger = logging.getLogger(__name__)


class LeadRepository:
    """Repository managing MongoDB persistence for BusinessLead and BusinessProfile documents."""

    def __init__(
        self,
        db: MongoDatabase = db_manager,
        config: MongoConfig = default_mongo_config,
    ) -> None:
        self.db = db
        self.config = config

    def _get_leads_coll(self) -> Any:
        return self.db.get_collection(self.config.leads_collection)

    def _get_profiles_coll(self) -> Any:
        return self.db.get_collection(self.config.profiles_collection)

    async def ensure_indexes(self) -> None:
        """Creates indexes for efficient lookup, deduplication, and scoring retrieval."""
        leads_coll = self._get_leads_coll()
        profiles_coll = self._get_profiles_coll()

        try:
            await leads_coll.create_index([("external_place_id", 1), ("source", 1)], name="idx_external_place_source")
            await leads_coll.create_index("phone", name="idx_phone")
            await leads_coll.create_index("website", name="idx_website")
            await leads_coll.create_index([("lead_score", -1)], name="idx_lead_score_desc")
            await leads_coll.create_index("priority", name="idx_priority")
            await leads_coll.create_index("created_at", name="idx_created_at")

            await profiles_coll.create_index("lead_id", name="idx_profile_lead_id")
            await profiles_coll.create_index("external_place_id", name="idx_profile_external_place_id")
            logger.info("MongoDB indexes verified successfully.")
        except Exception as exc:
            logger.warning("Could not ensure indexes: %s", str(exc))

    async def find_by_external_id(
        self, external_place_id: str, source: str
    ) -> Optional[BusinessLead]:
        """Finds a lead by its provider external place ID and source."""
        if not external_place_id:
            return None

        coll = self._get_leads_coll()
        doc = await coll.find_one({"external_place_id": external_place_id, "source": source})
        if doc:
            doc.pop("_id", None)
            return BusinessLead(**doc)
        return None

    async def find_duplicate(
        self,
        phone: Optional[str] = None,
        website: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Optional[BusinessLead]:
        """Searches for an existing lead matching phone, website, or normalized identity."""
        coll = self._get_leads_coll()

        query_conditions = []
        if phone:
            query_conditions.append({"phone": phone})
        if website:
            query_conditions.append({"website": website})

        if not query_conditions:
            return None

        doc = await coll.find_one({"$or": query_conditions})
        if doc:
            doc.pop("_id", None)
            return BusinessLead(**doc)
        return None

    async def save_or_merge_lead(self, lead: BusinessLead) -> BusinessLead:
        """
        Saves a new lead or merges newly available enrichment/scoring attributes
        into an existing lead record without overwriting non-null provider fields.
        """
        coll = self._get_leads_coll()
        now_iso = datetime.now(timezone.utc).isoformat()

        # Step 1: Look for existing lead by external ID or duplicate phone/website
        existing = None
        if lead.external_place_id:
            existing = await self.find_by_external_id(lead.external_place_id, lead.source)

        if not existing and (lead.phone or lead.website):
            existing = await self.find_duplicate(phone=lead.phone, website=lead.website, name=lead.name)

        lead_dict = lead.model_dump()

        if not existing:
            # New lead insertion
            lead_dict["created_at"] = now_iso
            lead_dict["updated_at"] = now_iso

            _id = lead.external_place_id or f"lead_{hash(lead.name)}"
            doc_to_save = {"_id": _id, **lead_dict}
            await coll.insert_one(doc_to_save)
            return BusinessLead(**lead_dict)

        # Existing lead merge logic
        merged_data = existing.model_dump()
        merged_data["updated_at"] = now_iso

        # Fill missing scalar fields non-destructively
        for k, v in lead_dict.items():
            if v is not None:
                if merged_data.get(k) is None:
                    merged_data[k] = v
                elif k in ("lead_score", "priority", "qualification_status", "score_breakdown", "website_status", "scrape_status", "contact_extraction_status"):
                    merged_data[k] = v

        # Merge dicts
        if lead_dict.get("social_links"):
            merged_data["social_links"] = {**(merged_data.get("social_links") or {}), **lead_dict["social_links"]}

        if lead_dict.get("raw_data"):
            merged_data["raw_data"] = {**(merged_data.get("raw_data") or {}), **lead_dict["raw_data"]}

        # Merge lists
        if lead_dict.get("services"):
            merged_data["services"] = list(set((merged_data.get("services") or []) + lead_dict["services"]))

        if lead_dict.get("contact_emails"):
            merged_data["contact_emails"] = list(set((merged_data.get("contact_emails") or []) + lead_dict["contact_emails"]))

        # Perform atomic update
        lookup_filter = {"_id": existing.external_place_id or f"lead_{hash(existing.name)}"}
        await coll.update_one(lookup_filter, {"$set": merged_data}, upsert=True)

        return BusinessLead(**merged_data)

    async def save_business_profile(self, profile: BusinessProfile) -> BusinessProfile:
        """Saves or updates a BusinessProfile document in MongoDB."""
        coll = self._get_profiles_coll()
        now_iso = datetime.now(timezone.utc).isoformat()
        prof_dict = profile.model_dump()

        _id = profile.lead_id or profile.external_place_id or f"profile_{hash(profile.business_name)}"
        prof_dict["updated_at"] = now_iso

        doc = {"_id": _id, **prof_dict}
        await coll.update_one({"_id": _id}, {"$set": doc, "$setOnInsert": {"created_at": now_iso}}, upsert=True)

        return profile

    async def find_profile_by_lead_id(self, lead_id: str) -> Optional[BusinessProfile]:
        """Finds a BusinessProfile document linked to a lead ID."""
        coll = self._get_profiles_coll()
        doc = await coll.find_one({"$or": [{"lead_id": lead_id}, {"external_place_id": lead_id}, {"_id": lead_id}]})
        if doc:
            doc.pop("_id", None)
            doc.pop("created_at", None)
            doc.pop("updated_at", None)
            return BusinessProfile(**doc)
        return None

    async def get_leads(
        self, filter_query: Optional[Dict[str, Any]] = None, skip: int = 0, limit: int = 50
    ) -> List[BusinessLead]:
        """Retrieves a list of BusinessLead documents matching filter criteria."""
        coll = self._get_leads_coll()
        cursor = await coll.find(filter_query or {}, skip=skip, limit=limit)
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            doc.pop("created_at", None)
            doc.pop("updated_at", None)
            results.append(BusinessLead(**doc))
        return results

    async def get_scored_leads(
        self, min_score: int = 0, priority: Optional[str] = None
    ) -> List[BusinessLead]:
        """Retrieves scored leads filtered by minimum score or priority rating."""
        query: Dict[str, Any] = {"lead_score": {"$gte": min_score}}
        if priority:
            query["priority"] = priority

        return await self.get_leads(filter_query=query)


default_lead_repository = LeadRepository()

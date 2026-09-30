"""LeadSutra lead discovery services package."""

from app.services.lead_discovery.base import BaseBusinessDiscoveryProvider
from app.services.lead_discovery.exceptions import (
    FoursquareAPIAuthenticationError,
    FoursquareAPIMalformedResponseError,
    FoursquareAPIQuotaError,
    FoursquareAPITimeoutError,
    FoursquareAPIUnavailableError,
    FoursquarePlacesAPIError,
    GoogleAPIAuthenticationError,
    GoogleAPIMalformedResponseError,
    GoogleAPIQuotaError,
    GoogleAPITimeoutError,
    GoogleAPIUnavailableError,
    GooglePlacesAPIError,
    LeadDiscoveryError,
)
from app.models.lead import BusinessSearchResponse
from app.services.lead_discovery.deduplication import (
    are_leads_duplicate,
    deduplicate_leads,
    merge_leads,
)
from app.services.lead_discovery.foursquare_places import FoursquarePlacesProvider
from app.services.lead_discovery.google_places import GooglePlacesProvider
from app.services.lead_discovery.normalizers import (
    haversine_distance_meters,
    normalize_address,
    normalize_business_name,
    normalize_phone,
    normalize_website_domain,
)
from app.services.lead_discovery.search_service import (
    BusinessSearchService,
    search_businesses,
    search_businesses_with_metadata,
)

__all__ = [
    "BaseBusinessDiscoveryProvider",
    "BusinessSearchResponse",
    "BusinessSearchService",
    "FoursquareAPIAuthenticationError",
    "FoursquareAPIMalformedResponseError",
    "FoursquareAPIQuotaError",
    "FoursquareAPITimeoutError",
    "FoursquareAPIUnavailableError",
    "FoursquarePlacesAPIError",
    "FoursquarePlacesProvider",
    "GoogleAPIAuthenticationError",
    "GoogleAPIMalformedResponseError",
    "GoogleAPIQuotaError",
    "GoogleAPITimeoutError",
    "GoogleAPIUnavailableError",
    "GooglePlacesAPIError",
    "GooglePlacesProvider",
    "LeadDiscoveryError",
    "are_leads_duplicate",
    "deduplicate_leads",
    "haversine_distance_meters",
    "merge_leads",
    "normalize_address",
    "normalize_business_name",
    "normalize_phone",
    "normalize_website_domain",
    "search_businesses",
    "search_businesses_with_metadata",
]

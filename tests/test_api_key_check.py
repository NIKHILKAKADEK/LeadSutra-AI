"""Diagnostic pytest file to check API key functionality for 1 lead."""

import os
import pytest
from dotenv import find_dotenv, load_dotenv

from app.models.lead import BusinessLead
from app.services.lead_discovery.foursquare_places import FoursquarePlacesProvider
from app.services.lead_discovery.google_places import GooglePlacesProvider


@pytest.mark.asyncio
async def test_check_google_key_single_lead():
    """Test fetching 1 lead using Google Places API key from .env."""
    load_dotenv(find_dotenv(usecwd=True), override=True)
    google_key = os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("GOOGLE_PLACES_API_KEY")
    if not google_key or "your_" in google_key.lower():
        pytest.skip("GOOGLE_MAPS_API_KEY is missing or unconfigured.")

    provider = GooglePlacesProvider(api_key=google_key)
    leads = await provider.search("restaurant", "Nashik, Maharashtra", limit=1)

    assert isinstance(leads, list)
    if leads:
        lead = leads[0]
        assert isinstance(lead, BusinessLead)
        print(f"\n[Google Lead] Name: {lead.name} | Phone: {lead.phone} | Email: {lead.email} | Address: {lead.address}")


@pytest.mark.asyncio
async def test_check_foursquare_key_single_lead():
    """Test fetching 1 lead using Foursquare Places API key from .env."""
    load_dotenv(find_dotenv(usecwd=True), override=True)
    fsq_key = os.getenv("FOURSQUARE_API_KEY")
    if not fsq_key or "your_" in fsq_key.lower():
        pytest.skip("FOURSQUARE_API_KEY is missing or unconfigured.")

    provider = FoursquarePlacesProvider(api_key=fsq_key)
    leads = await provider.search("restaurant", "Nashik, Maharashtra", limit=1)

    assert isinstance(leads, list)
    if leads:
        lead = leads[0]
        assert isinstance(lead, BusinessLead)
        print(f"\n[Foursquare Lead] Name: {lead.name} | Phone: {lead.phone} | Email: {lead.email} | Address: {lead.address}")

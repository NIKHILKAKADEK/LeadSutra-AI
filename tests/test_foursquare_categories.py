"""
Fetch up to 100 businesses from Foursquare that have
BOTH phone number and email.

The script searches multiple business categories in Nashik.

Usage:
    python fetch_100_leads.py YOUR_FOURSQUARE_API_KEY
"""

import sys
import requests
import time


# ============================================================
# SETTINGS
# ============================================================

LOCATION = "Nashik, Maharashtra"

TARGET_LEADS = 100

RESULTS_PER_REQUEST = 50

# Categories to search
CATEGORIES = [
    "restaurant",
    "cafe",
    "hotel",
    "gym",
    "salon",
    "real estate",
    "dentist",
    "clinic",
    "bakery",
    "coaching institute",
    "event planner",
    "car dealer",
]


# ============================================================
# FOURSQUARE SEARCH
# ============================================================

def search_category(api_key, category):

    print("\n" + "=" * 90)
    print(f"SEARCHING: {category.upper()}")
    print("=" * 90)

    url = "https://places-api.foursquare.com/places/search"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Places-Api-Version": "2025-06-17",
        "Accept": "application/json",
    }

    params = {
        "query": category,
        "near": LOCATION,
        "limit": RESULTS_PER_REQUEST,

        # Ask Foursquare for the fields we need
        "fields": (
            "fsq_place_id,"
            "name,"
            "location,"
            "tel,"
            "email,"
            "website,"
            "categories"
        ),
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=15
        )

    except requests.exceptions.RequestException as e:

        print(f"❌ Network error: {e}")

        return []

    print(f"Status code: {response.status_code}")

    if response.status_code != 200:

        print("❌ API request failed:")
        print(response.text[:1000])

        return []

    data = response.json()

    results = data.get(
        "results",
        []
    )

    print(
        f"Found {len(results)} "
        f"businesses from Foursquare"
    )

    return results


# ============================================================
# EXTRACT BUSINESS
# ============================================================

def extract_business(result, category):

    location = result.get(
        "location",
        {}
    )

    name = result.get(
        "name",
        "Unknown"
    )

    phone = result.get(
        "tel"
    )

    email = result.get(
        "email"
    )

    website = result.get(
        "website"
    )

    address = location.get(
        "formatted_address",
        "No address"
    )

    place_id = result.get(
        "fsq_place_id"
    )

    categories = result.get(
        "categories",
        []
    )

    category_names = []

    for cat in categories:

        cat_name = cat.get(
            "name"
        )

        if cat_name:
            category_names.append(
                cat_name
            )

    return {
        "id": place_id,
        "name": name,
        "category": category,
        "address": address,
        "phone": phone,
        "email": email,
        "website": website,
        "categories": ", ".join(
            category_names
        ),
    }


# ============================================================
# MAIN COLLECTION LOGIC
# ============================================================

def collect_leads(api_key):

    leads = []

    # Used to prevent duplicates
    seen_place_ids = set()

    for category in CATEGORIES:

        # Stop once we have 100
        if len(leads) >= TARGET_LEADS:
            break

        results = search_category(
            api_key,
            category
        )

        for result in results:

            business = extract_business(
                result,
                category
            )

            place_id = business["id"]

            # ------------------------------------------------
            # Skip duplicate businesses
            # ------------------------------------------------

            if place_id in seen_place_ids:
                continue

            seen_place_ids.add(
                place_id
            )

            # ------------------------------------------------
            # IMPORTANT:
            # Require BOTH phone AND email
            # ------------------------------------------------

            phone = business["phone"]
            email = business["email"]

            if not phone:
                continue

            if not email:
                continue

            # ------------------------------------------------
            # Valid lead
            # ------------------------------------------------

            leads.append(
                business
            )

            print(
                f"\n✅ QUALIFIED LEAD #{len(leads)}"
            )

            print(
                f"   Business : "
                f"{business['name']}"
            )

            print(
                f"   Category : "
                f"{business['category']}"
            )

            print(
                f"   Phone    : "
                f"{business['phone']}"
            )

            print(
                f"   Email    : "
                f"{business['email']}"
            )

            print(
                f"   Website  : "
                f"{business['website'] or 'None'}"
            )

            print(
                f"   Address  : "
                f"{business['address']}"
            )

            # ------------------------------------------------
            # Stop at 100
            # ------------------------------------------------

            if len(leads) >= TARGET_LEADS:
                break

        # Small delay between category requests
        time.sleep(0.5)

    return leads


# ============================================================
# PRINT FINAL RESULTS
# ============================================================

def print_results(leads):

    print("\n\n")
    print("=" * 100)
    print("FINAL QUALIFIED LEADS")
    print("=" * 100)

    print(
        f"\nTotal businesses having BOTH "
        f"phone + email: {len(leads)}"
    )

    print("\n")

    for i, lead in enumerate(
        leads,
        1
    ):

        print(
            f"{i}. {lead['name']}"
        )

        print(
            f"   Category : "
            f"{lead['category']}"
        )

        print(
            f"   Phone    : "
            f"{lead['phone']}"
        )

        print(
            f"   Email    : "
            f"{lead['email']}"
        )

        print(
            f"   Website  : "
            f"{lead['website'] or 'No website'}"
        )

        print(
            f"   Address  : "
            f"{lead['address']}"
        )

        print(
            f"   Foursquare ID: "
            f"{lead['id']}"
        )

        print("-" * 100)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    if len(sys.argv) != 2:

        print(
            "Usage:\n"
            "python fetch_100_leads.py "
            "YOUR_FOURSQUARE_API_KEY"
        )

        sys.exit(1)

    api_key = sys.argv[1]

    print("\n")
    print("=" * 90)
    print("LEADSUTRA - FOURSQUARE LEAD COLLECTION")
    print("=" * 90)

    print(
        f"\nLocation       : {LOCATION}"
    )

    print(
        f"Target leads   : {TARGET_LEADS}"
    )

    print(
        "Requirement    : Phone + Email"
    )

    leads = collect_leads(
        api_key
    )

    print_results(
        leads
    )

    print("\n")
    print("=" * 90)
    print("DONE")
    print("=" * 90)
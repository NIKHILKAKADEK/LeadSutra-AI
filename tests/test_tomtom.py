"""
Fetch restaurants and cafes using TomTom Search API.

Usage:
    python test_tomtom_categories.py YOUR_TOMTOM_API_KEY
"""

import sys
import requests


# ============================================================
# SETTINGS
# ============================================================

LATITUDE = 19.9975       # Nashik
LONGITUDE = 73.7898
RADIUS = 10000            # 10 km
LIMIT = 20


# ============================================================
# TOMTOM SEARCH
# ============================================================

def fetch_businesses(api_key, category):

    print("\n" + "=" * 90)
    print(f"TOMTOM - {category.upper()}")
    print("=" * 90)

    # TomTom search endpoint
    url = (
        "https://api.tomtom.com/search/2/search/"
        f"{category}.json"
    )

    params = {
        "key": api_key,
        "limit": LIMIT,
        "lat": LATITUDE,
        "lon": LONGITUDE,
        "radius": RADIUS,
        "relatedPois": "off",
    }

    try:
        response = requests.get(
            url,
            params=params,
            timeout=10
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

    results = data.get("results", [])

    print(
        f"✅ Found {len(results)} "
        f"{category}(s)"
    )

    businesses = []

    for i, result in enumerate(results, 1):

        poi = result.get("poi", {})
        address_data = result.get("address", {})

        name = poi.get(
            "name",
            "Unknown"
        )

        phone = poi.get(
            "phone",
            "No phone"
        )

        email = poi.get(
            "email",
            "No email"
        )

        website = poi.get(
            "url",
            "No website"
        )

        address = address_data.get(
            "freeformAddress",
            "No address"
        )

        business = {
            "name": name,
            "address": address,
            "phone": phone,
            "email": email,
            "website": website,
        }

        businesses.append(business)

        print(f"\n{i}. {name}")
        print(f"   Address : {address}")
        print(f"   Phone   : {phone}")
        print(f"   Email   : {email}")
        print(f"   Website : {website}")

    return businesses


# ============================================================
# SUMMARY
# ============================================================

def show_summary(category, businesses):

    total = len(businesses)

    phone_count = sum(
        1
        for b in businesses
        if b["phone"] != "No phone"
    )

    email_count = sum(
        1
        for b in businesses
        if b["email"] != "No email"
    )

    website_count = sum(
        1
        for b in businesses
        if b["website"] != "No website"
    )

    print("\n" + "-" * 70)
    print(f"{category.upper()} SUMMARY")
    print("-" * 70)

    print(f"Businesses found : {total}")
    print(f"Phone available  : {phone_count}")
    print(f"Email available  : {email_count}")
    print(f"Website available: {website_count}")

    if total > 0:

        print(
            f"Phone coverage   : "
            f"{phone_count / total * 100:.1f}%"
        )

        print(
            f"Email coverage   : "
            f"{email_count / total * 100:.1f}%"
        )

        print(
            f"Website coverage : "
            f"{website_count / total * 100:.1f}%"
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    if len(sys.argv) != 2:

        print(
            "Usage: "
            "python test_tomtom_categories.py "
            "YOUR_TOMTOM_API_KEY"
        )

        sys.exit(1)

    api_key = sys.argv[1]

    # --------------------------------------------------------
    # Restaurants
    # --------------------------------------------------------

    restaurants = fetch_businesses(
        api_key,
        "restaurant"
    )

    # --------------------------------------------------------
    # Cafes
    # --------------------------------------------------------

    cafes = fetch_businesses(
        api_key,
        "cafe"
    )

    # --------------------------------------------------------
    # Summaries
    # --------------------------------------------------------

    show_summary(
        "Restaurants",
        restaurants
    )

    show_summary(
        "Cafes",
        cafes
    )

    # --------------------------------------------------------
    # Overall comparison
    # --------------------------------------------------------

    print("\n" + "=" * 90)
    print("FINAL COMPARISON")
    print("=" * 90)

    print(
        f"\n{'Metric':<25}"
        f"{'Restaurants':<20}"
        f"{'Cafes':<20}"
    )

    print("-" * 65)

    print(
        f"{'Businesses found':<25}"
        f"{len(restaurants):<20}"
        f"{len(cafes):<20}"
    )

    restaurant_phone = sum(
        1 for b in restaurants
        if b["phone"] != "No phone"
    )

    cafe_phone = sum(
        1 for b in cafes
        if b["phone"] != "No phone"
    )

    restaurant_email = sum(
        1 for b in restaurants
        if b["email"] != "No email"
    )

    cafe_email = sum(
        1 for b in cafes
        if b["email"] != "No email"
    )

    restaurant_website = sum(
        1 for b in restaurants
        if b["website"] != "No website"
    )

    cafe_website = sum(
        1 for b in cafes
        if b["website"] != "No website"
    )

    print(
        f"{'Phone available':<25}"
        f"{restaurant_phone:<20}"
        f"{cafe_phone:<20}"
    )

    print(
        f"{'Email available':<25}"
        f"{restaurant_email:<20}"
        f"{cafe_email:<20}"
    )

    print(
        f"{'Website available':<25}"
        f"{restaurant_website:<20}"
        f"{cafe_website:<20}"
    )

    print("\n✅ Test complete.")
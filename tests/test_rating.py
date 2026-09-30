import requests


def main() -> None:
    API_KEY = "T1CKDMDLV5FDZMDJW5AUM24ZIW5PVH0GF4RCP2ZLY5UPRJRW"

    url = "https://places-api.foursquare.com/places/search"

    params = {
        "near": "Nashik, Maharashtra",
        "query": "restaurant",
        "sort": "RATING",
        "fields": "fsq_place_id,name,rating,tel,email,website,location",
        "limit": 50,
    }

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "X-Places-Api-Version": "2025-06-17",
        "Accept": "application/json",
    }

    response = requests.get(
        url,
        params=params,
        headers=headers,
    )

    print("Status:", response.status_code)

    if response.status_code != 200:
        print(response.text)
        return

    data = response.json()
    results = data.get("results", [])

    print(f"\nTotal businesses returned: {len(results)}")

    # Rating >= 8/10 = 4/5
    qualified = []

    for place in results:
        rating = place.get("rating")

        if rating is not None and rating >= 8.0:
            qualified.append(place)

    print(f"Businesses with rating >= 8.0/10: {len(qualified)}")

    print("\n" + "=" * 100)
    print("HIGH-RATED BUSINESSES")
    print("=" * 100)

    for i, place in enumerate(qualified, 1):
        name = place.get("name", "N/A")
        rating = place.get("rating", "N/A")
        phone = place.get("tel", "N/A")
        email = place.get("email", "N/A")
        website = place.get("website", "N/A")

        location = place.get("location", {})
        address = location.get("formatted_address", "N/A")

        rating_5 = round(rating / 2, 1) if isinstance(rating, (int, float)) else "N/A"

        print(f"\n{i}. {name}")
        print(f"   Rating  : {rating}/10 ({rating_5}/5)")
        print(f"   Phone   : {phone}")
        print(f"   Email   : {email}")
        print(f"   Website : {website}")
        print(f"   Address : {address}")


if __name__ == "__main__":
    main()
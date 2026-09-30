import requests


def main() -> None:
    API_KEY = "AIzaSyD5XnHJF3AANhe9MGex134fso3q4zR_S-s"
    url = "https://places.googleapis.com/v1/places:searchText"

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": "places.id,places.displayName",
    }

    body = {
        "textQuery": "restaurants in Nashik, Maharashtra",
        "pageSize": 5,
    }

    response = requests.post(
        url,
        headers=headers,
        json=body,
    )

    print("Status:", response.status_code)
    print(response.text)


if __name__ == "__main__":
    main()
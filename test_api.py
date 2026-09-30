import requests

API_KEY = "NJDOMA3ZUATTYTB55NZIR1JAZGL1BGNA3DB1RD22RZDDX2DU"

url = "https://places-api.foursquare.com/places/search"

params = {
    "near": "Nashik, Maharashtra",
    "query": "restaurant",
    "limit": 5
}

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "X-Places-Api-Version": "2025-06-17",
    "Accept": "application/json"
}

response = requests.get(
    url,
    params=params,
    headers=headers
)

print("Status:", response.status_code)
print(response.text)
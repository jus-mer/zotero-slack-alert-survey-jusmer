import os
import requests
import json

GROUP_ID = os.environ["GROUP_ID"]
ZOTERO_API_KEY = os.environ["ZOTERO_API_KEY"]
COLLECTION_KEY = os.environ.get("COLLECTION_KEY", "").strip()

headers = {
    "Zotero-API-Key": ZOTERO_API_KEY
}

url = (
    f"https://api.zotero.org/groups/{GROUP_ID}/items"
    f"?sort=dateAdded&direction=desc&limit=10"
)

response = requests.get(url, headers=headers, timeout=30)
response.raise_for_status()

items = response.json()

print(f"Items returned by group endpoint: {len(items)}")
print(f"Looking for collection: {COLLECTION_KEY}")
print()

for item in items:
    data = item.get("data", {})

    print("=" * 60)
    print("KEY:", item.get("key"))
    print("TITLE:", data.get("title"))
    print("DATE ADDED:", data.get("dateAdded"))
    print("COLLECTIONS:", data.get("collections"))
    print()

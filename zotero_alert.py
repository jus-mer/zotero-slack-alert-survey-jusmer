import os
import requests

GROUP_ID = os.environ["GROUP_ID"]
COLLECTION_KEY = os.environ["COLLECTION_KEY"]
ZOTERO_API_KEY = os.environ["ZOTERO_API_KEY"]
SLACK_WEBHOOK = os.environ["SLACK_WEBHOOK"]

LAST_ITEM_FILE = "last_item.txt"

headers = {
    "Zotero-API-Key": ZOTERO_API_KEY
}


def get_last_saved():
    try:
        with open(LAST_ITEM_FILE, "r") as f:
            return f.read().strip()
    except:
        return "none"


def save_last(key):
    with open(LAST_ITEM_FILE, "w") as f:
        f.write(key)


def format_authors(creators):
    authors = []

    for c in creators:
        if c.get("creatorType") == "author":
            first = c.get("firstName", "")
            last = c.get("lastName", "")
            authors.append(f"{first} {last}".strip())

    return ", ".join(authors) if authors else "Unknown authors"


def has_pdf(item_key):
    url = f"https://api.zotero.org/groups/{GROUP_ID}/items/{item_key}/children"

    r = requests.get(
        url,
        headers=headers,
        timeout=30
    )

    if not r.ok:
        return False

    for child in r.json():
        data = child.get("data", {})

        if (
            data.get("itemType") == "attachment"
            and data.get("contentType") == "application/pdf"
        ):
            return True

    return False


def get_creator_name(meta):
    created_by = meta.get("createdByUser") or {}

    if created_by.get("name"):
        return created_by["name"]

    if created_by.get("username"):
        return created_by["username"]

    if created_by.get("id"):
        return f"User ID {created_by['id']}"

    return "Not available"


def main():

    last_seen = get_last_saved()

    print("Monitoring collection:", COLLECTION_KEY)

    # IMPORTANT:
    # Use /items, because this endpoint returns the collection
    # memberships in data.collections.
    url = f"https://api.zotero.org/groups/{GROUP_ID}/items"

    params = {
        "sort": "dateAdded",
        "direction": "desc",
        "limit": 100,
        "include": "data"
    }

    r = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=30
    )

    r.raise_for_status()

    all_items = r.json()

    # Keep only top-level items belonging to our collection.
    items = []

    for item in all_items:
        data = item.get("data", {})

        collections = data.get("collections") or []

        if COLLECTION_KEY in collections:
            items.append(item)

    print("Items found in collection:", len(items))

    if not items:
        print("No items found.")
        return

    # Find items newer than the last one we processed.
    new_items = []

    for item in items:
        if item["key"] == last_seen:
            break

        new_items.append(item)

    if not new_items:
        print("No new items.")
        return

    # Oldest first
    new_items.reverse()

    for item in new_items:

        item_key = item["key"]
        data = item["data"]
        meta = item.get("meta", {})

        title = data.get("title", "No title")

        abstract = data.get(
            "abstractNote",
            ""
        ).strip()

        creators = data.get("creators", [])

        doi = data.get(
            "DOI",
            ""
        ).strip()

        authors = format_authors(creators)

        creator_name = get_creator_name(meta)

        zotero_link = (
            f"https://www.zotero.org/groups/"
            f"{GROUP_ID}/items/{item_key}"
        )

        pdf_status = "Yes" if has_pdf(item_key) else "No"

        if not abstract:
            abstract = "_No abstract available._"

        if doi:
            doi_link = f"https://doi.org/{doi}"
            doi_text = f"<{doi_link}|{doi}>"
        else:
            doi_text = "Not available"

        message = {
            "text":
                f"📚 *New Zotero item added*\n"
                f"*Title:* {title}\n"
                f"*Authors:* {authors}\n"
                f"*Added by:* {creator_name}\n"
                f"*DOI:* {doi_text}\n"
                f"*PDF attached:* {pdf_status}\n\n"
                f"*Abstract:*\n"
                f"{abstract[:1500]}\n\n"
                f"<{zotero_link}|Open in Zotero>"
        }

        slack_resp = requests.post(
            SLACK_WEBHOOK,
            json=message,
            timeout=15
        )

        if not slack_resp.ok:
            print(
                f"Slack webhook failed "
                f"({slack_resp.status_code}): "
                f"{slack_resp.text[:300]}"
            )

        print(f"Posted: {title}")

    # Save newest monitored item
    save_last(items[0]["key"])


if __name__ == "__main__":
    main()

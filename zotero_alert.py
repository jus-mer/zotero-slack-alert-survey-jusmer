import os
import requests
from datetime import datetime, timezone


# ============================================================
# Configuration
# ============================================================

GROUP_ID = os.environ["GROUP_ID"]
ZOTERO_API_KEY = os.environ["ZOTERO_API_KEY"]
SLACK_WEBHOOK = os.environ["SLACK_WEBHOOK"]
COLLECTION_KEY = os.environ.get("COLLECTION_KEY", "").strip()

if COLLECTION_KEY:
    LAST_ITEM_FILE = f"last_item_{COLLECTION_KEY}.txt"
else:
    LAST_ITEM_FILE = "last_item_group.txt"

ZOTERO_HEADERS = {
    "Zotero-API-Key": ZOTERO_API_KEY
}


# ============================================================
# State management
# ============================================================

def get_last_saved():
    """Return the last processed dateAdded timestamp."""

    if not os.path.exists(LAST_ITEM_FILE):
        return None

    with open(LAST_ITEM_FILE, "r", encoding="utf-8") as f:
        value = f.read().strip()

    return value or None


def save_last_saved(date_added):
    """Save the latest processed dateAdded timestamp."""

    with open(LAST_ITEM_FILE, "w", encoding="utf-8") as f:
        f.write(date_added)


def parse_date(date_string):
    """Convert a Zotero timestamp into a datetime."""

    if not date_string:
        return None

    return datetime.fromisoformat(
        date_string.replace("Z", "+00:00")
    )


# ============================================================
# Zotero
# ============================================================

def get_items():

    url = (
        f"https://api.zotero.org/groups/"
        f"{GROUP_ID}/items"
        f"?sort=dateAdded&direction=desc&limit=100"
    )

    if COLLECTION_KEY:
        print(f"Monitoring Zotero collection: {COLLECTION_KEY}")
        print(f"Collection key repr: {COLLECTION_KEY!r}")
    else:
        print(f"Monitoring entire Zotero group: {GROUP_ID}")

    response = requests.get(
        url,
        headers=ZOTERO_HEADERS,
        timeout=30
    )

    response.raise_for_status()

    items = response.json()

    print(f"Zotero returned {len(items)} items.")

    # --------------------------------------------------------
    # Filter by collection
    # --------------------------------------------------------

    if COLLECTION_KEY:

        filtered_items = []

        for item in items:

            data = item.get("data", {})
            collections = data.get("collections")

            if collections is None:
                collections = []

            # Make sure we are comparing strings.
            collections = [str(x).strip() for x in collections]

            if COLLECTION_KEY in collections:
                filtered_items.append(item)

        print(
            f"Found {len(filtered_items)} items in collection "
            f"{COLLECTION_KEY}."
        )

        # Diagnostic information for the first few matching items
        if filtered_items:
            print("Matching items:")

            for item in filtered_items[:10]:
                data = item.get("data", {})

                print(
                    f"  {item.get('key')} | "
                    f"{data.get('dateAdded')} | "
                    f"{data.get('title')}"
                )

        return filtered_items

    return items


# ============================================================
# Helpers
# ============================================================

def format_authors(creators):

    authors = []

    for creator in creators:

        if creator.get("creatorType") != "author":
            continue

        if creator.get("name"):
            authors.append(creator["name"])
        else:
            first = creator.get("firstName", "").strip()
            last = creator.get("lastName", "").strip()

            if first and last:
                authors.append(f"{first} {last}")
            elif last:
                authors.append(last)
            elif first:
                authors.append(first)

    return ", ".join(authors) if authors else "Unknown author"


def has_pdf(item_key):

    url = (
        f"https://api.zotero.org/groups/"
        f"{GROUP_ID}/items/{item_key}/children"
    )

    response = requests.get(
        url,
        headers=ZOTERO_HEADERS,
        timeout=30
    )

    response.raise_for_status()

    for child in response.json():

        data = child.get("data", {})

        if (
            data.get("itemType") == "attachment"
            and data.get("contentType") == "application/pdf"
        ):
            return True

    return False


# ============================================================
# Slack
# ============================================================

def post_to_slack(item):

    data = item.get("data", {})
    meta = item.get("meta", {})

    item_key = item.get("key")

    title = data.get("title") or "Untitled"

    authors = format_authors(
        data.get("creators", [])
    )

    doi = data.get("DOI")
    date_added = data.get("dateAdded")

    zotero_link = (
        f"https://www.zotero.org/groups/"
        f"{GROUP_ID}/items/{item_key}"
    )

    created_by = meta.get("createdByUser")

    if created_by:
        added_by = (
            created_by.get("name")
            or created_by.get("username")
            or "Unknown"
        )
    else:
        added_by = "Unknown"

    pdf = has_pdf(item_key)

    abstract = data.get("abstractNote", "").strip()

    message = (
        f"📚 *New Zotero item*\n\n"
        f"*{title}*\n\n"
        f"*Authors:* {authors}\n"
        f"*Added by:* {added_by}\n"
    )

    if date_added:
        message += f"*Date added:* {date_added}\n"

    if doi:
        message += f"*DOI:* {doi}\n"

    message += (
        f"*PDF:* {'Yes' if pdf else 'No'}\n"
    )

    if abstract:

        max_length = 1500

        if len(abstract) > max_length:
            abstract = (
                abstract[:max_length].rstrip()
                + "..."
            )

        message += (
            f"\n*Abstract:*\n{abstract}\n"
        )

    message += (
        f"\n<{zotero_link}|Open in Zotero>"
    )

    response = requests.post(
        SLACK_WEBHOOK,
        json={"text": message},
        timeout=30
    )

    response.raise_for_status()

    print(
        f"Slack notification sent for item {item_key}"
    )


# ============================================================
# Main
# ============================================================

def main():

    items = get_items()

    if not items:
        print("No Zotero items found.")
        return

    # Sort newest first
    items.sort(
        key=lambda item: (
            parse_date(
                item.get("data", {}).get("dateAdded")
            )
            or datetime.min.replace(tzinfo=timezone.utc)
        ),
        reverse=True
    )

    newest_item = items[0]

    newest_date = newest_item.get("data", {}).get("dateAdded")

    print(
        f"Newest item in monitored collection: "
        f"{newest_item.get('key')} | "
        f"{newest_date} | "
        f"{newest_item.get('data', {}).get('title')}"
    )

    last_saved = get_last_saved()

    # --------------------------------------------------------
    # First run
    # --------------------------------------------------------

    if last_saved is None:

        print("No previous state found.")

        if newest_date:
            save_last_saved(newest_date)

            print(
                f"Initialized state with {newest_date}."
            )

        return

    print(f"Last saved date: {last_saved}")

    last_date = parse_date(last_saved)

    # --------------------------------------------------------
    # Find new items
    # --------------------------------------------------------

    new_items = []

    for item in items:

        date_added = item.get("data", {}).get("dateAdded")

        item_date = parse_date(date_added)

        if item_date and item_date > last_date:
            new_items.append(item)

    if not new_items:

        print("No new Zotero items.")
        return

    print(
        f"Found {len(new_items)} new Zotero item(s)."
    )

    # --------------------------------------------------------
    # Send oldest -> newest
    # --------------------------------------------------------

    for item in reversed(new_items):

        item_type = item.get("data", {}).get("itemType")

        if item_type == "attachment":
            print(
                f"Skipping attachment {item.get('key')}"
            )
            continue

        post_to_slack(item)

    # --------------------------------------------------------
    # Save newest timestamp
    # --------------------------------------------------------

    if newest_date:

        save_last_saved(newest_date)

        print(
            f"Saved latest dateAdded: {newest_date}"
        )


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    main()

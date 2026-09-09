import os
import requests
from datetime import datetime


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
    """Convert Zotero ISO timestamp to a comparable datetime."""

    if not date_string:
        return None

    return datetime.fromisoformat(
        date_string.replace("Z", "+00:00")
    )


# ============================================================
# Zotero helpers
# ============================================================

def format_authors(creators):
    """Format Zotero creators as a readable author string."""

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

    if not authors:
        return "Unknown author"

    return ", ".join(authors)


def has_pdf(item_key):
    """Check whether a Zotero item has a PDF attachment."""

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

    children = response.json()

    for child in children:
        data = child.get("data", {})

        if (
            data.get("itemType") == "attachment"
            and data.get("contentType") == "application/pdf"
        ):
            return True

    return False


def get_items():
    """
    Retrieve recent items from the Zotero group and,
    if requested, filter them to the selected collection.
    """

    url = (
        f"https://api.zotero.org/groups/"
        f"{GROUP_ID}/items"
        f"?sort=dateAdded&direction=desc&limit=100"
    )

    if COLLECTION_KEY:
        print(
            f"Monitoring Zotero collection: {COLLECTION_KEY}"
        )
    else:
        print(
            f"Monitoring entire Zotero group: {GROUP_ID}"
        )

    response = requests.get(
        url,
        headers=ZOTERO_HEADERS,
        timeout=30
    )

    response.raise_for_status()

    items = response.json()

    if COLLECTION_KEY:
        filtered_items = []

        for item in items:
            data = item.get("data", {})
            collections = data.get("collections") or []

            if COLLECTION_KEY in collections:
                filtered_items.append(item)

        print(
            f"Found {len(filtered_items)} recent items "
            f"in collection {COLLECTION_KEY}"
        )

        return filtered_items

    return items


# ============================================================
# Slack
# ============================================================

def post_to_slack(item):
    """Send a formatted notification to Slack."""

    data = item.get("data", {})
    meta = item.get("meta", {})

    title = data.get("title") or "Untitled"

    authors = format_authors(
        data.get("creators", [])
    )

    doi = data.get("DOI")
    date_added = data.get("dateAdded")
    item_key = item.get("key")

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
        max_abstract_length = 1500

        if len(abstract) > max_abstract_length:
            abstract = (
                abstract[:max_abstract_length].rstrip()
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

    # Sort explicitly by dateAdded, newest first.
    items.sort(
        key=lambda item: parse_date(
            item.get("data", {}).get("dateAdded")
        ) or datetime.min.astimezone(),
        reverse=True
    )

    last_saved = get_last_saved()

    # --------------------------------------------------------
    # First run:
    #
    # Initialize the state without sending notifications for
    # existing items.
    # --------------------------------------------------------

    if last_saved is None:

        newest_date = items[0]["data"].get("dateAdded")

        if newest_date:
            save_last_saved(newest_date)

            print(
                f"No previous state found. "
                f"Initialized state with {newest_date}."
            )

        return

    last_date = parse_date(last_saved)

    # --------------------------------------------------------
    # Find items added after the last processed timestamp.
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
            continue

        post_to_slack(item)

    # --------------------------------------------------------
    # Save timestamp of newest item processed.
    # --------------------------------------------------------

    newest_date = items[0]["data"].get("dateAdded")

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

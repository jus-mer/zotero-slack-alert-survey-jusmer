import os
import requests


# ============================================================
# Configuration
# ============================================================

GROUP_ID = os.environ["GROUP_ID"]
ZOTERO_API_KEY = os.environ["ZOTERO_API_KEY"]
SLACK_WEBHOOK = os.environ["SLACK_WEBHOOK"]

# Optional:
# If COLLECTION_KEY is set, only items belonging to that
# collection are monitored.
# If empty, the entire Zotero group is monitored.
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
    """Return the last processed Zotero item key."""
    if not os.path.exists(LAST_ITEM_FILE):
        return None

    with open(LAST_ITEM_FILE, "r", encoding="utf-8") as f:
        value = f.read().strip()

    return value or None


def save_last_saved(item_key):
    """Save the most recently processed item key."""
    with open(LAST_ITEM_FILE, "w", encoding="utf-8") as f:
        f.write(item_key)


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
    Retrieve recent items from the Zotero group.

    Zotero's direct collection-items endpoint is returning 404
    for this collection, even though the collection exists.

    Therefore we retrieve recent group items and filter them
    locally according to their collection memberships.
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

    # --------------------------------------------------------
    # If a collection is specified, filter the group items
    # according to their collection memberships.
    # --------------------------------------------------------

    if COLLECTION_KEY:
        filtered_items = []

        for item in items:
            data = item.get("data", {})

            collections = data.get("collections", [])

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

    # --------------------------------------------------------
    # Construct Slack message
    # --------------------------------------------------------

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
        # Keep Slack messages reasonably short.
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

    payload = {
        "text": message
    }

    response = requests.post(
        SLACK_WEBHOOK,
        json=payload,
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

    last_saved = get_last_saved()

    # --------------------------------------------------------
    # First run
    #
    # If there is no saved state, do NOT send notifications
    # for all existing items. Instead, initialize the state
    # with the newest item.
    # --------------------------------------------------------

    if last_saved is None:

        newest_item = items[0]
        newest_key = newest_item.get("key")

        if newest_key:
            save_last_saved(newest_key)

            print(
                f"No previous state found. "
                f"Initialized state with item {newest_key}."
            )

        return

    # --------------------------------------------------------
    # Find items newer than the last processed item.
    #
    # Items are sorted newest first, so we stop when we reach
    # the previously processed item.
    # --------------------------------------------------------

    new_items = []

    for item in items:

        item_key = item.get("key")

        if item_key == last_saved:
            break

        new_items.append(item)

    if not new_items:
        print("No new Zotero items.")
        return

    print(
        f"Found {len(new_items)} new Zotero item(s)."
    )

    # --------------------------------------------------------
    # Send notifications oldest -> newest
    # --------------------------------------------------------

    for item in reversed(new_items):

        item_type = item.get("data", {}).get("itemType")

        # Skip attachment items.
        if item_type == "attachment":
            continue

        post_to_slack(item)

    # --------------------------------------------------------
    # Save the newest item that was returned.
    # --------------------------------------------------------

    newest_key = items[0].get("key")

    if newest_key:
        save_last_saved(newest_key)

        print(
            f"Saved latest Zotero item: {newest_key}"
        )


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    main()

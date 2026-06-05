import os
import json
import time
import googleapiclient.discovery
import google_auth_oauthlib.flow

CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ["https://www.googleapis.com/auth/youtube"]
SUBSCRIPTION_CACHE_FILE = "subscription_ids_cache.json"
CATEGORIZED_FILE = "youtube_channels_categorized.json"
SECONDS_BETWEEN_REQUESTS = 0.2
# Each subscriptions.delete costs 50 quota units; daily limit is 10,000.
QUOTA_COST_PER_DELETE = 50


def authenticate_youtube():
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, SCOPES)
    credentials = flow.run_local_server(port=0)
    return googleapiclient.discovery.build("youtube", "v3", credentials=credentials)


def fetch_subscriptions(youtube):
    """Return a dict mapping channel title → subscription ID."""
    print("Fetching your subscriptions from YouTube...")
    subs = {}
    next_page_token = None

    while True:
        time.sleep(SECONDS_BETWEEN_REQUESTS)
        response = youtube.subscriptions().list(
            part="snippet",
            mine=True,
            maxResults=50,
            pageToken=next_page_token
        ).execute()

        for item in response.get("items", []):
            title = item["snippet"]["title"]
            sub_id = item["id"]
            subs[title] = sub_id

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    print(f"Found {len(subs)} subscriptions.")
    return subs


def load_subscription_cache():
    try:
        with open(SUBSCRIPTION_CACHE_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_subscription_cache(subs):
    with open(SUBSCRIPTION_CACHE_FILE, "w") as f:
        json.dump(subs, f, indent=2)


def get_subscriptions(youtube, refresh=False):
    if not refresh:
        cached = load_subscription_cache()
        if cached:
            print(f"Loaded {len(cached)} subscriptions from cache.")
            return cached
    subs = fetch_subscriptions(youtube)
    save_subscription_cache(subs)
    return subs


def load_categories():
    """Load category → [channel names] from the categorized JSON if it exists."""
    try:
        with open(CATEGORIZED_FILE, "r") as f:
            data = json.load(f)
        return data.get("summary", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def print_separator():
    print("-" * 50)


def pick_channels_from_list(channels, subs):
    """Show a numbered list of channels and return the ones the user selects."""
    available = [ch for ch in channels if ch in subs]
    if not available:
        print("  (none of these channels are in your current subscriptions)")
        return []

    for i, name in enumerate(available, 1):
        print(f"  {i:>3}. {name}")

    print()
    raw = input("Enter numbers to remove (comma-separated), or press Enter to skip: ").strip()
    if not raw:
        return []

    selected = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(available):
                selected.append(available[idx])
            else:
                print(f"  Skipping out-of-range number: {part}")
        else:
            print(f"  Skipping invalid entry: '{part}'")

    return selected


def browse_by_category(subs, categories):
    to_remove = []

    category_names = list(categories.keys())
    while True:
        print_separator()
        print("CATEGORIES  (channels still subscribed / total in category)")
        print_separator()
        for i, cat in enumerate(category_names, 1):
            channels = categories[cat]
            still_subbed = sum(1 for ch in channels if ch in subs)
            print(f"  {i:>3}. {cat}  ({still_subbed}/{len(channels)})")
        print()
        print("  Enter a category number to browse it.")
        print("  Press Enter when done browsing categories.")

        raw = input("> ").strip()
        if not raw:
            break
        if not raw.isdigit() or not (1 <= int(raw) <= len(category_names)):
            print("Invalid selection.")
            continue

        cat = category_names[int(raw) - 1]
        print_separator()
        print(f"Category: {cat}")
        print_separator()
        selected = pick_channels_from_list(categories[cat], subs)
        if selected:
            to_remove.extend(selected)
            print(f"  Added to removal list: {', '.join(selected)}")

    return to_remove


def search_channels(subs):
    to_remove = []

    while True:
        print_separator()
        query = input("Search channel name (or press Enter to stop): ").strip().lower()
        if not query:
            break

        matches = [name for name in subs if query in name.lower()]
        if not matches:
            print("  No matches found.")
            continue

        selected = pick_channels_from_list(matches, subs)
        if selected:
            to_remove.extend(selected)
            print(f"  Added to removal list: {', '.join(selected)}")

    return to_remove


def unsubscribe(youtube, subs, to_remove):
    if not to_remove:
        print("Nothing to remove.")
        return

    # Deduplicate while preserving order
    seen = set()
    unique = [ch for ch in to_remove if not (ch in seen or seen.add(ch))]

    print_separator()
    print(f"Channels queued for removal ({len(unique)}):")
    for name in unique:
        print(f"  - {name}")

    quota_cost = len(unique) * QUOTA_COST_PER_DELETE
    print(f"\nEstimated quota cost: {quota_cost} units  (daily limit: 10,000)")
    confirm = input("\nType 'yes' to confirm unsubscribe, or anything else to cancel: ").strip().lower()
    if confirm != "yes":
        print("Cancelled.")
        return

    print()
    removed = []
    failed = []
    for name in unique:
        sub_id = subs.get(name)
        if not sub_id:
            print(f"  SKIP (not found in subscriptions): {name}")
            continue
        try:
            time.sleep(SECONDS_BETWEEN_REQUESTS)
            youtube.subscriptions().delete(id=sub_id).execute()
            del subs[name]
            removed.append(name)
            print(f"  Unsubscribed: {name}")
        except Exception as e:
            failed.append(name)
            print(f"  FAILED: {name}  ({e})")

    save_subscription_cache(subs)
    print_separator()
    print(f"Done. Removed: {len(removed)}  |  Failed: {len(failed)}")
    if failed:
        print("Failed channels:", ", ".join(failed))


def main():
    print("YouTube Unsubscribe Tool")
    print("========================")

    youtube = authenticate_youtube()

    refresh = input("Refresh subscription list from YouTube? (y/n, default n): ").strip().lower() == "y"
    subs = get_subscriptions(youtube, refresh=refresh)

    if not subs:
        print("No subscriptions found.")
        return

    categories = load_categories()
    to_remove = []

    while True:
        print_separator()
        print("What would you like to do?")
        print("  1. Browse channels by category")
        print("  2. Search channels by name")
        print("  3. Review removal list and unsubscribe")
        print("  4. Quit without changes")
        print()
        if to_remove:
            unique_count = len(set(to_remove))
            print(f"  Removal list: {unique_count} channel(s) queued")
            print()

        choice = input("> ").strip()

        if choice == "1":
            if not categories:
                print("No categorized data found. Run categorize_channels.py first, or use search.")
            else:
                selected = browse_by_category(subs, categories)
                to_remove.extend(selected)

        elif choice == "2":
            selected = search_channels(subs)
            to_remove.extend(selected)

        elif choice == "3":
            unsubscribe(youtube, subs, to_remove)
            to_remove = []

        elif choice == "4":
            print("Exiting without changes.")
            break

        else:
            print("Invalid choice.")


if __name__ == "__main__":
    main()

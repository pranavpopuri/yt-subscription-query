import os
import json
import time

import streamlit as st
import pandas as pd
import googleapiclient.discovery
import google_auth_oauthlib.flow

# ── Config ─────────────────────────────────────────────────────────────────────
CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ["https://www.googleapis.com/auth/youtube"]  # covers readonly ops too
CATEGORIZED_FILE = "youtube_channels_categorized.json"
SUBSCRIPTION_CACHE_FILE = "subscription_ids_cache.json"
CHANNEL_URLS_CACHE_FILE = "channel_urls_cache.json"
CATEGORIES_CONFIG_FILE = "categories_config.json"
QUOTA_COST_PER_DELETE = 50

st.set_page_config(page_title="YouTube Manager", page_icon="▶", layout="wide")

# ── Auth ───────────────────────────────────────────────────────────────────────
def authenticate():
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, SCOPES
    )
    credentials = flow.run_local_server(port=0)
    return googleapiclient.discovery.build("youtube", "v3", credentials=credentials)

def fetch_subs_with_channel_ids(youtube):
    """Fetch subscriptions and return (title→sub_id, title→videos_page_url)."""
    subs, channel_urls = {}, {}
    next_page_token = None
    while True:
        time.sleep(0.2)
        response = youtube.subscriptions().list(
            part="snippet", mine=True, maxResults=50, pageToken=next_page_token
        ).execute()
        for item in response.get("items", []):
            title = item["snippet"]["title"]
            channel_id = item["snippet"]["resourceId"]["channelId"]
            subs[title] = item["id"]
            channel_urls[title] = f"https://www.youtube.com/channel/{channel_id}/videos"
        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break
    return subs, channel_urls

def load_channel_urls_cache():
    try:
        with open(CHANNEL_URLS_CACHE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_channel_urls_cache(urls):
    with open(CHANNEL_URLS_CACHE_FILE, "w") as f:
        json.dump(urls, f, indent=2)

def load_categories_config():
    try:
        with open(CATEGORIES_CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"specialized": {}, "medium": {}, "broad": {}}

def save_categories_config(config):
    with open(CATEGORIES_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

# ── Session state ──────────────────────────────────────────────────────────────
defaults = {
    "youtube": None,
    "subs": {},
    "channel_urls": {},
    "categories": {},
    "categories_config": None,
    "search_results": [],
    "to_remove": set(),
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

if st.session_state.categories_config is None:
    st.session_state.categories_config = load_categories_config()

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("▶ YouTube Manager")
    st.divider()
    if st.session_state.youtube is None:
        st.warning("Not authenticated")
        if st.button("Sign in with Google", type="primary", use_container_width=True):
            with st.spinner("Opening browser…"):
                st.session_state.youtube = authenticate()
            st.rerun()
    else:
        st.success("Signed in")
        if st.button("Switch account", use_container_width=True):
            st.session_state.youtube = authenticate()
            st.rerun()
    st.divider()
    st.caption("Daily quota: **10,000 units**")
    st.caption("Deletions cost 50 units each → max ~160/day")

if st.session_state.youtube is None:
    st.title("YouTube Manager")
    st.info("Sign in with Google in the sidebar to get started.")
    st.stop()

youtube = st.session_state.youtube

tab_cats, tab_categorize, tab_search, tab_unsub = st.tabs([
    "Categories", "Categorize Channels", "Search Videos", "Unsubscribe"
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Categories editor
# ══════════════════════════════════════════════════════════════════════════════
with tab_cats:
    st.header("Categories")
    st.info(
        "**How it works:** Each channel's title + description are scanned with whole-word "
        "keyword matching. Tiers are checked in order — **Specialized first** — so the first "
        "match wins and lower tiers are never reached.\n\n"
        "**Subcategories:** Add them to Specialized with specific keywords. For example, "
        "adding *embedded systems* with keywords `embedded, microcontroller, firmware` means "
        "those channels match that label instead of the broad *programming* category."
    )

    config = st.session_state.categories_config

    st.subheader("Match thresholds")
    st.caption("Minimum number of keyword hits required before a category is assigned. "
               "Raise the broad threshold to reduce false positives from generic words.")
    min_matches = config.get("min_matches", {"specialized": 1, "medium": 1, "broad": 2})
    th_cols = st.columns(3)
    th_cols[0].number_input("Specialized", min_value=1, max_value=10,
                            value=min_matches.get("specialized", 1), key="mm_specialized")
    th_cols[1].number_input("Medium",      min_value=1, max_value=10,
                            value=min_matches.get("medium", 1),      key="mm_medium")
    th_cols[2].number_input("Broad",       min_value=1, max_value=10,
                            value=min_matches.get("broad", 2),       key="mm_broad")
    st.divider()

    TIER_META = [
        ("specialized", "Specialized",
         "Checked first — put subcategories and highly specific topics here."),
        ("medium",      "Medium",
         "Checked second — moderately specific topics."),
        ("broad",       "Broad",
         "Checked last — wide umbrella terms like 'programming' or 'fitness'."),
    ]

    for tier_key, tier_label, tier_desc in TIER_META:
        st.subheader(tier_label)
        st.caption(tier_desc)

        for cat in list(config.get(tier_key, {}).keys()):
            keywords = config[tier_key][cat]
            with st.expander(f"{cat}  ({len(keywords)} keywords)"):
                st.text_area(
                    "Keywords (comma-separated, whole-word matched)",
                    value=", ".join(keywords),
                    key=f"kw_{tier_key}__{cat}",
                )
                if st.button("Remove category", key=f"rm_{tier_key}__{cat}"):
                    del st.session_state.categories_config[tier_key][cat]
                    save_categories_config(st.session_state.categories_config)
                    st.rerun()

        with st.form(key=f"form_add_{tier_key}", clear_on_submit=True):
            c1, c2, c3 = st.columns([2, 4, 1])
            new_name = c1.text_input("New category name", key=f"new_name_{tier_key}")
            new_kws  = c2.text_input("Keywords (comma-separated)", key=f"new_kws_{tier_key}")
            if c3.form_submit_button("Add", use_container_width=True) and new_name.strip():
                kws = [k.strip() for k in new_kws.split(",") if k.strip()]
                st.session_state.categories_config[tier_key][new_name.strip()] = kws
                save_categories_config(st.session_state.categories_config)
                st.rerun()

        st.divider()

    if st.button("Save changes", type="primary"):
        new_config = {tk: {} for tk, _, _ in TIER_META}
        new_config["min_matches"] = {
            "specialized": st.session_state.mm_specialized,
            "medium":      st.session_state.mm_medium,
            "broad":       st.session_state.mm_broad,
        }
        for tier_key, _, _ in TIER_META:
            for cat in st.session_state.categories_config.get(tier_key, {}):
                raw = st.session_state.get(f"kw_{tier_key}__{cat}", "")
                kws = [k.strip() for k in raw.split(",") if k.strip()]
                if kws:
                    new_config[tier_key][cat] = kws
        st.session_state.categories_config = new_config
        save_categories_config(new_config)
        st.success("Saved to categories_config.json")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Categorize Channels
# ══════════════════════════════════════════════════════════════════════════════
with tab_categorize:
    from categorize_channels import (
        get_all_subscribed_channels,
        categorize_channel,
        load_categories_config,
        export_to_json,
        QuotaTracker,
        OUTPUT_JSON,
    )
    from youtube_search import get_video_sample_text, load_cache, save_cache

    st.header("Categorize Channels")
    st.caption("Groups all your subscriptions by topic and saves the result for the Unsubscribe tab.")

    if st.button("Fetch & Categorize", type="primary"):
        quota_tracker = QuotaTracker()

        with st.spinner("Fetching subscriptions from YouTube…"):
            channels = get_all_subscribed_channels(youtube, quota_tracker)

        config = load_categories_config()
        cache = load_cache()

        # Pass 1: categorize from description + title
        progress = st.progress(0, text="Categorizing channels…")
        temp_categories = {}
        for i, channel in enumerate(channels):
            progress.progress((i + 1) / len(channels), text=f"Categorizing: {channel['title'][:40]}")
            desc = channel["description"].strip()
            title = channel["title"]
            if not desc:
                category = "no description"
            else:
                category = categorize_channel(desc, title, config=config)
                if category == "miscellaneous":
                    category = categorize_channel("", title, config=config, title_only=True)
            temp_categories.setdefault(category, []).append(channel)
        progress.empty()

        # Pass 2: sample 5 videos for anything still uncategorized
        unresolved = (
            temp_categories.pop("no description", []) +
            temp_categories.pop("miscellaneous", [])
        )
        if unresolved:
            progress2 = st.progress(0, text=f"Sampling videos for {len(unresolved)} uncategorized channels…")
            for i, channel in enumerate(unresolved):
                progress2.progress(
                    (i + 1) / len(unresolved),
                    text=f"Sampling: {channel['title'][:40]}"
                )
                sample = get_video_sample_text(youtube, channel["id"], cache)
                if sample:
                    category = categorize_channel(sample, channel["title"], config=config)
                else:
                    category = "miscellaneous"
                temp_categories.setdefault(category, []).append(channel)
            progress2.empty()
            save_cache(cache)

        ordered = ["no description", "miscellaneous"] + [
            c for c in temp_categories if c not in ("no description", "miscellaneous")
        ]
        categorized = {
            "metadata": {
                "total_channels": len(channels),
                "api_quota_used": quota_tracker.get_quota_used(),
                "categories_count": {},
            },
            "channels": {},
        }
        for cat in ordered:
            ch_list = temp_categories.get(cat, [])
            categorized["metadata"]["categories_count"][cat] = len(ch_list)
            categorized["channels"][cat] = ch_list

        export_to_json(categorized, OUTPUT_JSON, ordered)
        st.session_state.categories = {
            cat: [ch["title"] for ch in temp_categories.get(cat, [])]
            for cat in ordered
        }
        st.success(
            f"Categorized {len(channels)} channels · "
            f"{quota_tracker.get_quota_used()} quota units used"
        )

    # Load from file if not in session
    cats = st.session_state.categories
    if not cats and os.path.exists(OUTPUT_JSON):
        with open(OUTPUT_JSON) as f:
            cats = json.load(f).get("summary", {})
        st.session_state.categories = cats

    if cats:
        st.divider()
        total = sum(len(v) for v in cats.values())
        st.caption(f"{total} channels · {len(cats)} categories")

        chart_data = {k: len(v) for k, v in cats.items() if v}
        st.bar_chart(chart_data, x_label="Category", y_label="Channels")

        for category, channels in cats.items():
            if not channels:
                continue
            with st.expander(f"{category}  ({len(channels)})"):
                cols = st.columns(3)
                for i, name in enumerate(sorted(channels)):
                    cols[i % 3].write(name)

        # ── Miscellaneous inspector ────────────────────────────────────────────
        if os.path.exists(OUTPUT_JSON):
            with open(OUTPUT_JSON) as f:
                detail = json.load(f).get("detailed_data", {}).get("by_category", {})
            misc = detail.get("miscellaneous", [])
            if misc:
                st.divider()
                st.subheader(f"Miscellaneous inspector  ({len(misc)} channels)")
                st.caption(
                    "These channels didn't match any category. Browse their descriptions "
                    "to find keywords worth adding in the Categories tab."
                )
                filter_q = st.text_input(
                    "Filter by name or description",
                    placeholder="Search…",
                    key="misc_filter",
                )
                filtered = misc
                if filter_q:
                    q = filter_q.lower()
                    filtered = [
                        ch for ch in misc
                        if q in ch["title"].lower() or q in ch.get("description", "").lower()
                    ]
                st.caption(f"Showing {min(len(filtered), 100)} of {len(filtered)}")
                for ch in filtered[:100]:
                    with st.expander(ch["title"]):
                        desc = ch.get("description", "").strip()
                        st.write(desc if desc else "*(no description)*")
                        st.link_button("Open channel", ch["url"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Search Videos
# ══════════════════════════════════════════════════════════════════════════════
with tab_search:
    from youtube_search import (
        get_subscribed_channels,
        get_channel_metadata,
        get_channel_playlists,
        get_channel_relevance_score,
        search_channel_videos,
        load_cache,
        save_cache,
        MAX_RELEVANT_CHANNELS,
    )

    st.header("Search Videos")
    st.caption("Finds relevant videos across your subscribed channels without using the expensive search.list API.")

    query = st.text_input("Search query", placeholder="e.g. dynamic programming, transformer architecture")

    with st.expander("Scoring weights & limits"):
        c1, c2, c3, c4 = st.columns(4)
        desc_w = c1.slider("Description", 0.0, 2.0, 1.0, 0.05,
                           help="Weight for full-description semantic similarity")
        kw_w   = c2.slider("Keywords",    0.0, 1.0, 0.25, 0.05,
                           help="Weight for keyword matches in description")
        title_w = c3.slider("Title",      0.0, 1.0, 0.1, 0.05,
                            help="Weight for title similarity (only used when description is empty)")
        playlist_w = c4.slider("Playlists", 0.0, 1.0, 0.5, 0.05,
                               help="Weight for playlist title matches")
        max_channels = st.slider("Max channels to search", 1, MAX_RELEVANT_CHANNELS, 20)

    if st.button("Search", type="primary", disabled=not bool(query)):
        weights = {
            "description_weight": desc_w,
            "keyword_weight": kw_w,
            "title_weight": title_w,
            "playlist_weight": playlist_w,
        }
        cache = load_cache()

        with st.spinner("Loading subscriptions…"):
            channels = get_subscribed_channels(youtube, cache)

        # Rank channels with a progress bar
        rank_progress = st.progress(0, text=f"Ranking {len(channels)} channels…")
        channel_scores = []
        for i, channel in enumerate(channels):
            rank_progress.progress((i + 1) / len(channels),
                                   text=f"Ranking: {channel['title'][:40]}")
            metadata = get_channel_metadata(youtube, channel["id"], cache)
            if not metadata:
                continue
            playlist_titles = get_channel_playlists(youtube, channel["id"], cache)
            score = get_channel_relevance_score(metadata, query, weights, playlist_titles)
            channel_scores.append((score, channel))
        channel_scores.sort(reverse=True, key=lambda x: x[0]["total_score"])
        relevant = channel_scores[:max_channels]
        rank_progress.empty()
        save_cache(cache)

        # Search each channel
        results = []
        search_progress = st.progress(0, text="Searching channels…")
        for i, (score_details, channel) in enumerate(relevant):
            search_progress.progress(
                (i + 1) / len(relevant),
                text=f"Searching: {channel['title'][:40]}"
            )
            videos = search_channel_videos(youtube, channel, query, cache)
            results.extend(videos[:20])
        search_progress.empty()
        save_cache(cache)

        st.session_state.search_results = results
        st.success(f"Found {len(results)} videos across {len(relevant)} channels")

    if st.session_state.search_results:
        results = st.session_state.search_results
        df = pd.DataFrame(results)[["title", "channel", "views", "duration", "published_at", "url"]]
        df = df.sort_values("views", ascending=False).reset_index(drop=True)

        st.dataframe(
            df,
            column_config={
                "title":        st.column_config.TextColumn("Title", width="large"),
                "channel":      st.column_config.TextColumn("Channel"),
                "views":        st.column_config.NumberColumn("Views", format="%d"),
                "duration":     st.column_config.TextColumn("Duration"),
                "published_at": st.column_config.TextColumn("Published"),
                "url":          st.column_config.LinkColumn("Link", display_text="Watch"),
            },
            use_container_width=True,
            hide_index=True,
        )

        csv = df.drop(columns=["url"]).to_csv(index=False)
        st.download_button("Download CSV", csv, "search_results.csv", "text/csv")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Unsubscribe
# ══════════════════════════════════════════════════════════════════════════════
with tab_unsub:
    from unsubscribe import (
        load_subscription_cache,
        save_subscription_cache,
        SECONDS_BETWEEN_REQUESTS,
    )

    st.header("Unsubscribe")
    st.caption("Browse by category or search by name, then remove channels in bulk.")

    # Load / refresh subscriptions
    c1, c2 = st.columns([1, 5])
    if c1.button("Refresh from YouTube"):
        with st.spinner("Fetching subscriptions…"):
            subs, channel_urls = fetch_subs_with_channel_ids(youtube)
            save_subscription_cache(subs)
            save_channel_urls_cache(channel_urls)
            st.session_state.subs = subs
            st.session_state.channel_urls = channel_urls
        st.success(f"Loaded {len(subs)} subscriptions.")

    if not st.session_state.subs:
        cached = load_subscription_cache()
        if cached:
            st.session_state.subs = cached
            if not st.session_state.channel_urls:
                st.session_state.channel_urls = load_channel_urls_cache()
            c2.caption(f"{len(cached)} subscriptions loaded from cache.")
        else:
            st.info("Click 'Refresh from YouTube' to load your subscriptions.")
            st.stop()

    subs = st.session_state.subs

    # Load categories
    cats = st.session_state.categories
    if not cats and os.path.exists(CATEGORIZED_FILE):
        with open(CATEGORIZED_FILE) as f:
            cats = json.load(f).get("summary", {})

    mode = st.radio("Browse by", ["Category", "Name search"], horizontal=True)

    def channel_rows(names, key_prefix):
        """Render a checkbox + videos-page link for each channel. Returns checked names."""
        checked = []
        for name in sorted(names):
            url = st.session_state.channel_urls.get(name)
            c1, c2 = st.columns([1, 14])
            if c1.checkbox("", key=f"{key_prefix}_{name}", label_visibility="collapsed"):
                checked.append(name)
            label = f"[{name}]({url})" if url else name
            c2.markdown(label)
        return checked

    if mode == "Category":
        if not cats:
            st.warning("No categorized data found — run the Categorize Channels tab first.")
        else:
            for cat, channels in cats.items():
                available = [ch for ch in channels if ch in subs]
                if not available:
                    continue
                with st.expander(f"{cat}  ({len(available)} subscribed)"):
                    checked = channel_rows(available, f"cat_{cat}")
                    if checked and st.button(f"Add {len(checked)} to removal list", key=f"add_{cat}"):
                        st.session_state.to_remove.update(checked)
                        st.rerun()
    else:
        name_query = st.text_input("Channel name", placeholder="Type to search…")
        if name_query:
            matches = [n for n in subs if name_query.lower() in n.lower()]
            if matches:
                checked = channel_rows(matches, "search")
                if checked and st.button(f"Add {len(checked)} to removal list"):
                    st.session_state.to_remove.update(checked)
                    st.rerun()
            else:
                st.caption("No matches found.")

    # ── Removal list ───────────────────────────────────────────────────────────
    if st.session_state.to_remove:
        st.divider()
        to_remove = sorted(st.session_state.to_remove)
        quota_cost = len(to_remove) * QUOTA_COST_PER_DELETE

        st.subheader(f"Queued for removal  ({len(to_remove)})")
        st.caption(f"Quota cost: **{quota_cost}** of your 10,000 daily units")

        if quota_cost > 10000:
            st.error("This exceeds the daily quota limit. Reduce the list before proceeding.")

        # Show list with individual remove buttons
        for name in to_remove:
            c1, c2 = st.columns([8, 1])
            c1.write(name)
            if c2.button("✕", key=f"rm_{name}"):
                st.session_state.to_remove.discard(name)
                st.rerun()

        st.divider()
        c1, c2 = st.columns(2)
        if c1.button("Clear list", use_container_width=True):
            st.session_state.to_remove.clear()
            st.rerun()

        if c2.button("Unsubscribe from all", type="primary", use_container_width=True,
                     disabled=quota_cost > 10000):
            removed, failed = [], []
            progress = st.progress(0, text="Unsubscribing…")
            for i, name in enumerate(to_remove):
                progress.progress((i + 1) / len(to_remove), text=f"Removing: {name[:40]}")
                sub_id = subs.get(name)
                if not sub_id:
                    failed.append(name)
                    continue
                try:
                    time.sleep(SECONDS_BETWEEN_REQUESTS)
                    youtube.subscriptions().delete(id=sub_id).execute()
                    del subs[name]
                    removed.append(name)
                except Exception as e:
                    failed.append(f"{name} ({e})")

            save_subscription_cache(subs)
            st.session_state.subs = subs
            st.session_state.to_remove.clear()
            progress.empty()

            if removed:
                st.success(f"Unsubscribed from {len(removed)} channel(s).")
            if failed:
                st.error("Failed: " + ", ".join(failed))

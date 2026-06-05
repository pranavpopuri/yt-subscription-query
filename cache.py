import json
import os
from datetime import datetime

_DIR = "cache"


def _path(name):
    return os.path.join(_DIR, name)


def _read(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(path, data):
    os.makedirs(_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ── Subscriptions ──────────────────────────────────────────────────────────────
# Stores the channel list used by search and categorize.
# Shape: { last_fetched: str|None, channels: [{id, title}, ...] }

def load_subscriptions():
    return _read(_path("subscriptions.json"), {"channels": [], "last_fetched": None})

def save_subscriptions(channels):
    _write(_path("subscriptions.json"), {
        "channels": channels,
        "last_fetched": datetime.now().isoformat(),
    })


# ── Channel metadata ───────────────────────────────────────────────────────────
# Channel title, description, and extracted core_topics, keyed by channel_id.
# Shape: { channel_id: {title, description, core_topics}, ... }

def load_channel_metadata():
    return _read(_path("channel_metadata.json"), {})

def save_channel_metadata(data):
    _write(_path("channel_metadata.json"), data)


# ── Playlist names ─────────────────────────────────────────────────────────────
# All playlist titles per channel, keyed by channel_id.
# Shape: { channel_id: ["Playlist Title", ...], ... }

def load_playlist_names():
    return _read(_path("playlist_names.json"), {})

def save_playlist_names(data):
    _write(_path("playlist_names.json"), data)


# ── Video samples ──────────────────────────────────────────────────────────────
# Sample text (titles + descriptions from recent videos) for channels with no
# description. Used by categorization. Keyed by channel_id.
# Shape: { channel_id: "sample text...", ... }

def load_video_samples():
    return _read(_path("video_samples.json"), {})

def save_video_samples(data):
    _write(_path("video_samples.json"), data)


# ── Subscription IDs ───────────────────────────────────────────────────────────
# Maps channel title → subscription ID for the unsubscribe flow.
# Shape: { last_fetched: str|None, ids: {"Channel Name": "sub_id", ...} }

def load_subscription_ids():
    data = _read(_path("subscription_ids.json"), {"ids": {}, "last_fetched": None})
    # handle flat format from the old subscription_ids_cache.json
    if "ids" not in data:
        return {"ids": data, "last_fetched": None}
    return data

def save_subscription_ids(ids):
    _write(_path("subscription_ids.json"), {
        "ids": ids,
        "last_fetched": datetime.now().isoformat(),
    })


# ── Channel URLs ───────────────────────────────────────────────────────────────
# Maps channel title → videos page URL for the unsubscribe tab.
# Shape: { "Channel Name": "https://...", ... }

def load_channel_urls():
    return _read(_path("channel_urls.json"), {})

def save_channel_urls(data):
    _write(_path("channel_urls.json"), data)

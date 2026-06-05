# Caching

All cache files live in the `cache/` directory as JSON. Nothing is cached in memory across runs — everything is loaded from disk at the start of each operation and saved back when done.

---

## Files

### `video_index.json`
The primary cache. Built from the Search tab ("Build index" button).

```
{
  channel_id: {
    channel_title: str,
    last_fetched: ISO 8601 string,
    videos: [{ id, title, published_at }]
  }
}
```

Up to 200 recent video titles per channel. Used by:
- **Fast search** — TF-IDF over video titles
- **Categorization Pass 2** — keyword matching over video titles for unresolved channels

Refresh is incremental: only videos newer than `last_fetched` are fetched per channel.

### `playlist_index.json`
Built alongside the video index.

```
{
  channel_id: {
    channel_title: str,
    last_fetched: ISO 8601 string,
    playlists: [{ id, title }]
  }
}
```

Stores playlist IDs (needed to construct URLs) and titles. Used by playlist search. Fully rebuilt on every refresh since playlists have no reliable ordering by publish date.

### `subscriptions.json`
```
{ last_fetched: str, channels: [{ id, title }] }
```

The flat channel list used by both search and categorization. Avoids re-fetching the full subscription list on every run.

### `channel_metadata.json`
```
{ channel_id: { title, description, core_topics } }
```

Used by deep (channel-first) search to rank channels by description relevance. `core_topics` is a list of nouns extracted from the description at fetch time.

### `playlist_names.json`
```
{ channel_id: ["Playlist Title", ...] }
```

Playlist titles only (no IDs). Used by deep search as an additional scoring signal. Separate from `playlist_index.json` which stores IDs for linking.

### `subscription_ids.json`
```
{ last_fetched: str, ids: { "Channel Name": "subscription_id" } }
```

Maps channel name to YouTube subscription ID. Required to call `subscriptions.delete` in the Unsubscribe tab.

### `channel_urls.json`
```
{ "Channel Name": "https://youtube.com/channel/.../videos" }
```

Maps channel name to its videos page URL for display in the Unsubscribe tab.

---

## What is not cached

- **Channel descriptions from the subscriptions API** — fetched fresh every categorization run. Descriptions can change and are cheap to fetch (1 quota unit per 50 channels).
- **Video sample text for categorization** — previously stored in `video_samples.json`, now removed. Pass 2 reads from `video_index.json` instead, which has timestamps and covers more videos. Stale cached descriptions were causing incorrect categorizations.

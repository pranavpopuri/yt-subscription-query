# YouTube Data API v3 — Quota Reference

Daily quota: **10,000 units** per Google Cloud project, resets at midnight Pacific Time.

---

## API Call Costs

| Method | Cost | Where Used |
|---|---|---|
| `subscriptions.list` | 1 unit per page (50 subs/page) | Both scripts |
| `subscriptions.delete` | **50 units** per channel | `unsubscribe.py` |
| `channels.list` (any part) | 1 unit per call | `youtube_search.py` |
| `playlists.list` | 1 unit per call (50 playlists/page) | `youtube_search.py` |
| `playlistItems.list` | 1 unit per page (50 videos/page) | `youtube_search.py` |
| `videos.list` | 1 unit per 50 videos | `youtube_search.py` |
| `search.list` | 100 units per call | **Not used** (avoided by fetching uploads playlist directly) |

---

## Estimated Quota Per Run

### `youtube_search.py` (e.g. 300 subscriptions, processing top 50 channels)

| Operation | Units |
|---|---|
| Fetch all subscriptions (300 ÷ 50/page) | ~6 |
| Evaluate all 300 channels for relevance (`channels.list`) | ~300 |
| Fetch uploads playlist ID for top 50 channels | ~50 |
| Fetch all videos for top 50 channels (~500 avg, 10 pages each) | ~500 |
| Fetch video details for relevant videos | ~50–150 |
| **Total** | **~900–1,000 units** |

Can run roughly **10 times per day** before hitting the limit.

### `unsubscribe.py`

| Deletions | Units Used |
|---|---|
| 10 channels | 500 |
| 100 channels | 5,000 |
| 160 channels | 8,000 |
| 200 channels | 10,000 ← hits daily limit |

Safe daily cap: **~160 channel deletions** (leaves headroom for list calls).

---

## Known Bug in Quota Estimator

`estimate_channel_quota_usage()` in `youtube_search.py` (line 600) adds `100` units for `channels.list`, but `channels.list` only costs **1 unit**. The 100-unit cost belongs to `search.list`, which is not used. In-script quota estimates are therefore inflated.

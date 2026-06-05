# Search

Two search modes are available in the Search Videos tab. Both search only within your subscribed channels.

---

## Fast (Index)

Searches cached video titles and playlist titles locally. Costs ~2 quota units regardless of how many channels you're subscribed to (one `videos.list` batch to fetch view counts for the top candidates).

**How it works:**

1. All video titles from `video_index.json` and playlist titles from `playlist_index.json` are loaded into memory.
2. Each title is tokenized, stemmed (Porter stemmer), and stop words removed.
3. The query goes through the same stemming pipeline.
4. TF-IDF cosine similarity scores every title against the query.
5. Top 100 video candidates are fetched for view counts (`videos.list`), then re-ranked by `relevance_score × log10(views)` so popular videos beat obscure ones with the same keyword match.
6. Top 50 playlist matches are returned ranked by relevance score only (no view count signal for playlists).

**Stemming** means "transformer" and "transformers" are the same token (`transform`), so searches match word-form variants automatically — the same behaviour as keyword matching in categorization.

**Requires the index to be built.** Build it once from the "Search index" expander; refresh incrementally to pick up new videos.

---

## Deep (Channel-First)

Ranks all subscribed channels by how well their description matches the query, then fetches and filters actual videos from the top N channels. Costs ~500+ quota units depending on how many channels and videos are processed.

**How it works:**

1. Channel descriptions are scored using TF-IDF semantic similarity + keyword matching + playlist title matching, weighted by configurable sliders.
2. Top N channels (default 20, max 50) are selected.
3. For each channel, the uploads playlist is fetched and filtered by date (last 365 days) and keyword relevance.
4. Video details (duration, view count) are fetched in batches. Videos shorter than 1 min or longer than 5 hours, or with under 300 views, are dropped.
5. Results across all channels are merged and sorted by view count.

---

## Choosing a Mode

| | Fast | Deep |
|---|---|---|
| Quota cost | ~2 units | ~500+ units |
| Requires index | Yes | No |
| Searches by | Video/playlist titles | Channel descriptions + video content |
| Best for | Specific topics with clear title keywords | Broad topics where channel relevance matters |

Fast mode is the right default. Use Deep when Fast returns too few results or when the topic is better described by channel content than individual video titles.

---

## Playlist Search

Playlist search runs automatically alongside Fast mode. Results appear in a separate table above the video results. Playlists are scored by TF-IDF cosine similarity only (no view count re-ranking). Only available in Fast mode since playlist IDs are stored in the playlist index.

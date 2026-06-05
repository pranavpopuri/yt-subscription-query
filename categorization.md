# Categorization

## Pipeline Overview

Channels are categorized in two passes. Pass 1 is free (no API calls). Pass 2 costs quota only for channels not in the video index.

---

## Pass 1 — Description + Title

The channel's description and title are concatenated and matched against keyword tiers. If the description is empty or the result is miscellaneous, a title-only retry runs with threshold forced to 1 (titles are too short to reliably hit a multi-keyword threshold).

Specialized is checked first, so subcategories always beat their parent umbrella term — a channel about embedded systems never slips into programming even if it mentions Python.

## Pass 2 — Video Titles

Runs only for channels that are still unresolved (no description, or miscellaneous after Pass 1). Pulls video titles from the video index (up to 200 titles per channel, zero quota) and runs the same keyword matcher on that text. If a channel isn't in the video index, falls back to a live API fetch of 20 recent video titles (costs 2 quota units).

Video sample text is never cached separately — the video index is the single source of truth for this data.

---

## Stemming

Before any matching, both the channel text and every keyword are reduced to their root form via Porter stemmer. "robots", "robotic", and "robotics" all become `robot`, so keyword lists stay small without manual variants. Stemming is applied symmetrically to both sides.

Word stems are memoized with `@lru_cache` — each unique word is stemmed exactly once per run.

---

## Tier Priority

```
Specialized → Medium → Broad
```

A channel matches exactly one category — whichever tier produces the first hit. Subcategories belong in Specialized precisely so they beat their parent umbrella in Broad.

---

## Min-Match Threshold

A category only applies when at least `min_matches[tier]` distinct keywords are found in the stemmed text. Configurable per tier in the Categories tab. Raising Broad to 2 requires two independent keyword hits before assigning a broad category, reducing false positives from channels that mention a keyword incidentally.

---

## Debug Log

After each categorization run, the Streamlit UI shows a per-channel log with:

- **pass** — 1 (description/title) or 2 (video titles)
- **signal** — what data was used: `description`, `title-only`, `index (N videos)`, `API`, or `none`
- **category** — the assigned category
- **reason** — which tier matched and which keywords hit, or `no tier matched`

---

## Known Limitations

- **Coincidental keyword matches** — a lifestyle channel mentioning "recipe" once gets filed under food/cooking. Use the miscellaneous inspector to catch these.
- **Multi-category channels** — first-match-wins means a channel covering both ML and data science is assigned to whichever appears first in Specialized.
- **Non-English descriptions** — Porter stemmer is English-only. Foreign-language channels almost always end up in miscellaneous.
- **Video index coverage** — Pass 2 accuracy depends on the index being built and reasonably fresh. Channels absent from the index fall back to 20 live API videos.

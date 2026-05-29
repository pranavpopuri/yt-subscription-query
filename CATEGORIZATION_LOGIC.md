# Categorization Logic

## Pipeline Overview

Channels are categorized through up to three passes, each more expensive but only
triggered if the previous pass fails.

---

## Pass 1 — Description + Title

The channel's description and title are concatenated and matched against all keyword
tiers. Specialized is checked first, so subcategories always beat their parent umbrella
term (e.g. a channel about embedded systems can never slip into programming even if it
mentions Python).

## Pass 2 — Title Only

Runs only if Pass 1 returns miscellaneous. Uses `title_only=True`, which forces
threshold 1 across all tiers regardless of config. Short titles can't reliably
hit 2 keywords, so the threshold is relaxed here.

## Pass 3 — Video Sampling

Runs only if both prior passes fail. Fetches 5 recent video titles + descriptions
(2 quota units per channel, cached after the first run) and runs the same matcher
on that combined text. This is the last resort.

---

## Stemming

Before any matching, both the channel text and every keyword are reduced to their
root form via Porter stemmer. "robots", "robotic", and "robotics" all become `robot`,
so keyword lists stay small and canonical without manual variants. Stemming is applied
symmetrically to both sides, so no new false positives are introduced.

Word stems are cached with `@lru_cache` — each unique word is stemmed exactly once
per run regardless of how many channels or keywords reference it.

---

## Tier Priority

```
Specialized → Medium → Broad
```

A channel matches exactly one category — whichever tier produces the first hit.
This prevents a data science channel from also matching programming just because
it mentions Python. Subcategories belong in Specialized precisely so they beat
their parent umbrella in Broad.

---

## Min-Match Threshold

A category only applies when at least `min_matches[tier]` distinct keywords are
found in the stemmed text. Currently 1 for all tiers. Can be raised per-tier in
the Categories tab — raising Broad to 2 would require two independent keyword hits
before assigning a broad category, reducing false positives from channels that
mention a keyword only incidentally.

---

## Known Limitations

- **Coincidental keyword matches** — a lifestyle channel mentioning "recipe" once
  gets filed under food/cooking. Irreducible with keyword matching. Use the
  miscellaneous inspector to catch these.
- **Multi-category channels** — first-match-wins means a channel covering both ML
  and data science is assigned to whichever appears first in Specialized.
- **Non-English descriptions** — Porter stemmer is English-only. Foreign-language
  channels almost always end up in miscellaneous regardless of content.

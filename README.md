# YouTube Manager

A Streamlit app for managing your YouTube subscriptions — search videos across your subscribed channels, categorize channels by topic, and bulk-unsubscribe, all without hitting the expensive `search.list` API.

## Features

- **Search Videos** — find relevant videos across your subscriptions using channel description matching and keyword scoring
- **Categorize Channels** — auto-group your subscriptions by topic using a configurable keyword taxonomy
- **Unsubscribe** — bulk-remove channels by category or name search, with live quota cost tracking
- **Categories Editor** — add, edit, and tune keyword categories without touching code

## Prerequisites

- Python 3.9+
- A Google account with YouTube subscriptions
- Your own Google Cloud OAuth2 credentials (see below — free, takes ~5 minutes)

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/pranavpopuri/yt-subscription-query.git
cd yt-subscription-query
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

Then download the required NLTK data:

```python
python -c "import nltk; nltk.download('punkt'); nltk.download('averaged_perceptron_tagger'); nltk.download('stopwords'); nltk.download('punkt_tab'); nltk.download('averaged_perceptron_tagger_eng')"
```

### 3. Create Google Cloud credentials

You need your own credentials because the app authenticates as **you** to access your own YouTube account. This is free and takes about 5 minutes.

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new project (or use an existing one)
2. In the left sidebar, go to **APIs & Services → Library**
3. Search for **YouTube Data API v3** and click **Enable**
4. Go to **APIs & Services → Credentials**
5. Click **Create Credentials → OAuth 2.0 Client ID**
6. If prompted, configure the OAuth consent screen first:
   - User type: **External**
   - Fill in app name and your email — the other fields are optional
   - Add the scope `https://www.googleapis.com/auth/youtube`
   - Add your Google account email as a **test user**
7. Back on Create Credentials, choose application type: **Desktop app**
8. Click **Create**, then **Download JSON**
9. Rename the downloaded file to `client_secret.json` and place it in the project root

### 4. Run the app

```bash
streamlit run app.py
```

A browser window will open. Click **Sign in with Google** in the sidebar, complete the OAuth flow, and you're ready to go.

## Quota

The YouTube Data API gives each project **10,000 units per day**, resetting at midnight Pacific Time.

| Operation | Cost |
|---|---|
| Fetch all subscriptions | ~6 units (300 subs) |
| Rank channels for a search | ~1 unit per channel |
| Search videos across 20 channels | ~200–400 units |
| Categorize all channels | ~1 unit per channel |
| Unsubscribe from a channel | 50 units each |

Typical search run: ~500–700 units. You can comfortably run several searches per day. Results are cached so re-running the same search costs nothing for channel metadata.

## Project structure

```
app.py                        # Streamlit UI
categorize_channels.py        # Channel categorization logic
youtube_search.py             # Video search logic
unsubscribe.py                # Unsubscribe helpers
categories_config.json        # Keyword taxonomy (edit via the UI)
client_secret.json            # Your OAuth credentials (gitignored — never committed)
```

## Notes

- `client_secret.json` is gitignored and will never be committed
- On first run you'll be asked to authorize the app in your browser; subsequent runs reuse the cached token
- The daily quota is per Google Cloud project, so each user runs against their own separate limit

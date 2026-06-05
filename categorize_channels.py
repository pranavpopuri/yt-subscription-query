import json
import re
import ssl
import time
from functools import lru_cache
from nltk.stem import PorterStemmer
from youtube_search import get_video_sample_text
import cache as cache_mod

_stemmer = PorterStemmer()


def _execute_with_retry(request, max_retries=3):
    for attempt in range(max_retries):
        try:
            return request.execute()
        except ssl.SSLError:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)

@lru_cache(maxsize=None)
def _stem_word(word: str) -> str:
    return _stemmer.stem(word)

def _stem(text: str) -> str:
    """Stem every word in text so keyword matching is form-agnostic."""
    return ' '.join(_stem_word(w) for w in re.findall(r'[a-z]+', text.lower()))

OUTPUT_JSON = "youtube_channels_categorized.json"
CATEGORIES_CONFIG_FILE = "categories_config.json"

# YouTube API quota costs
QUOTA_COSTS = {
    'subscriptions.list': 1,   # per page (50 items)
    'channels.list': 1,
    'playlistItems.list': 1,   # per page (50 items)
}


class QuotaTracker:
    def __init__(self):
        self.quota_used = 0

    def add_quota(self, endpoint):
        self.quota_used += QUOTA_COSTS.get(endpoint, 0)

    def get_quota_used(self):
        return self.quota_used



def get_all_subscribed_channels(youtube, quota_tracker):
    channels = []
    next_page_token = None

    while True:
        quota_tracker.add_quota('subscriptions.list')
        response = _execute_with_retry(youtube.subscriptions().list(
            part="snippet",
            mine=True,
            maxResults=50,
            pageToken=next_page_token
        ))

        for item in response['items']:
            channels.append({
                'id': item['snippet']['resourceId']['channelId'],
                'title': item['snippet']['title'],
                'description': item['snippet']['description'],
                'url': f"https://youtube.com/channel/{item['snippet']['resourceId']['channelId']}"
            })

        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break

    return channels


def load_categories_config():
    try:
        with open(CATEGORIES_CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def categorize_channel(description, title, config=None, title_only=False):
    """Categorization with priority tiers loaded from categories_config.json.

    Both the channel text and each keyword are stemmed before matching, so
    word-form variants (robot/robots/robotic/robotics, code/coding/coder, etc.)
    all resolve to the same stem and match each other automatically.

    Pass title_only=True to force threshold 1 across all tiers — titles are
    too short to reliably hit the configured broad threshold.
    """
    if config is None:
        config = load_categories_config()
    if config is None:
        return 'miscellaneous'

    stemmed_text = _stem(f"{title} {description}")

    if title_only:
        min_matches = {"specialized": 1, "medium": 1, "broad": 1}
    else:
        min_matches = config.get("min_matches", {"specialized": 1, "medium": 1, "broad": 1})

    for tier in ["specialized", "medium", "broad"]:
        threshold = min_matches.get(tier, 1)
        for category, keywords in config.get(tier, {}).items():
            hits = sum(
                1 for kw in keywords
                if re.search(r'\b' + re.escape(_stem(kw)) + r'\b', stemmed_text)
            )
            if hits >= threshold:
                return category
    return 'miscellaneous'



def export_to_json(categorized_data, filename, ordered_categories):
    # Create quick-access summary with "no description" first
    summary = {
        category: [channel['title'] for channel in categorized_data['channels'][category]]
        for category in ordered_categories
    }

    # Reorganize the data structure
    export_data = {
        'summary': summary,  # Quick category:channel_names lookup
        'metadata': categorized_data['metadata'],
        'detailed_data': {
            'by_category': {category: categorized_data['channels'][category] for category in ordered_categories},
            'all_channels': [
                channel
                for category in ordered_categories
                for channel in categorized_data['channels'][category]
            ]
        }
    }

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)
    print(f"\nExported categorized channels to {filename}")


def main():
    import auth

    quota_tracker = QuotaTracker()
    youtube = auth.build_youtube()

    print("Fetching ALL your subscribed channels...")
    channels = get_all_subscribed_channels(youtube, quota_tracker)
    print(f"Found {len(channels)} subscribed channels.")

    categorized = {
        'metadata': {
            'total_channels': len(channels),
            'api_quota_used': quota_tracker.get_quota_used(),
            'categories_count': {}
        },
        'channels': {}
    }

    config = load_categories_config()
    video_samples = cache_mod.load_video_samples()

    # Pass 1: categorize from channel description + title
    temp_categories = {}
    for channel in channels:
        desc = channel['description'].strip()
        title = channel['title']
        if not desc:
            category = 'no description'
        else:
            category = categorize_channel(desc, title, config=config)
            if category == 'miscellaneous':
                category = categorize_channel('', title, config=config, title_only=True)
        temp_categories.setdefault(category, []).append(channel)

    # Pass 2: for anything still uncategorized, sample 5 recent videos and retry
    unresolved = (
        temp_categories.pop('no description', []) +
        temp_categories.pop('miscellaneous', [])
    )
    if unresolved:
        print(f"\nSampling videos for {len(unresolved)} uncategorized channels...")
        for channel in unresolved:
            sample = get_video_sample_text(youtube, channel['id'], video_samples)
            if sample:
                quota_tracker.add_quota('channels.list')
                quota_tracker.add_quota('playlistItems.list')
                category = categorize_channel(sample, channel['title'], config=config)
            else:
                category = 'miscellaneous'
            temp_categories.setdefault(category, []).append(channel)
        cache_mod.save_video_samples(video_samples)

    # Ensure "no description" is first in the export
    all_categories = list(temp_categories.keys())
    ordered_categories = ['no description', 'miscellaneous'] + [
        cat for cat in all_categories if cat not in ('no description', 'miscellaneous')
    ]

    # Organize for export
    for category in ordered_categories:
        channel_list = temp_categories.get(category, [])
        categorized['metadata']['categories_count'][category] = len(channel_list)
        categorized['channels'][category] = channel_list

    # Print summary to console
    print("\nCategory Summary:")
    for category in ordered_categories:
        count = categorized['metadata']['categories_count'][category]
        print(f"{category}: {count} channels")

    # Export to JSON
    export_to_json(categorized, OUTPUT_JSON, ordered_categories)

    print(f"\nTotal YouTube API quota units used: {quota_tracker.get_quota_used()}")
    print("Note: YouTube's free quota is 10,000 units per day")


if __name__ == "__main__":
    main()

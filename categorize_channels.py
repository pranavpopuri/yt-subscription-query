import os
import json
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import re
from pathlib import Path

# Configuration
CLIENT_SECRETS_FILE = "C:\\Users\\hipra\\Downloads\\client_secret_REDACTED_CLIENT_ID.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
OUTPUT_JSON = "youtube_channels_categorized.json"

# YouTube API quota costs
QUOTA_COSTS = {
    'subscriptions.list': 1,  # per page (50 items)
}


class QuotaTracker:
    def __init__(self):
        self.quota_used = 0

    def add_quota(self, endpoint):
        self.quota_used += QUOTA_COSTS.get(endpoint, 0)

    def get_quota_used(self):
        return self.quota_used


def get_authenticated_service():
    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, SCOPES)
    credentials = flow.run_local_server(port=0)
    return build('youtube', 'v3', credentials=credentials)


def get_all_subscribed_channels(youtube, quota_tracker):
    channels = []
    next_page_token = None

    while True:
        quota_tracker.add_quota('subscriptions.list')
        response = youtube.subscriptions().list(
            part="snippet",
            mine=True,
            maxResults=50,
            pageToken=next_page_token
        ).execute()

        for item in response['items']:
            channels.append({
                'id': item['snippet']['resourceId']['channelId'],
                'title': item['snippet']['title'],
                'description': item['snippet']['description'].lower(),
                'url': f"https://youtube.com/channel/{item['snippet']['resourceId']['channelId']}"
            })

        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break

    return channels


def categorize_channel(description, title):
  """Categorization with all categories in priority tiers, allowing whole word matches only."""
  full_text = f"{title.lower()} {description.lower()}"

  # Tier 1: Most specific categories (checked first)
  specialized_categories = {
    'leetcode': ['leetcode', 'interview', 'competitive programming', 'algorithm', 'algorithms'],
    'machine learning': ['machine learning', 'deep learning', 'neural network', 'llm', 'computer vision', 'ai'],
    'data science': ['data science', 'data analysis', 'data visualization', 'data pipeline', 'data'],
    'robotics': ['robotics', 'autonomous', 'slam'],
    'CAD': ['cad', 'computer aided design', 'solidworks', 'fusion 360', 'design', '3d'],
    'chess': ['chess', 'grandmaster', 'chess opening', 'endgame'],
    'basketball': ['basketball', 'nba', 'wnba', 'hoops'],
    'cybersecurity': ['cybersecurity']
  }

  # Tier 2: Medium specificity
  medium_categories = {
    'statistics': ['statistics', 'stats', 'probability', 'regression'],
    'math': ['math', 'mathematics', 'linear algebra', 'number theory'],
    'Cars/machines': ['cars', 'automotive', 'engine', 'vehicle dynamics', 'racing', 'car'],
    'video games': ['video games', 'game development', 'speedrun', ],
    'music': ['music production', 'audio engineering', 'music theory', 'music'],
    'economics': ['economics']
  }

  # Tier 3: Broad categories (last resort)
  broad_categories = {
    'programming': ['programming', 'development', 'coding', 'code', 'tech', 'computers', 'computer science', 'computer', 'software', 'software engineering', 'java', 'c++', 'python', 'linux', 'app', 'windows', 'mac'],
    'engineering': ['engineering', 'mechanical', 'aerospace', 'engineer'],
    'STEM': ['stem', 'science education', 'technology', 'physics', 'chemistry'],
    'food/cooking': ['cooking', 'food recipe', 'culinary arts', 'cook', 'chef', 'baker', 'baking', 'desserts', 'dessert', 'food'],
    'Fitness': ['fitness', 'workout routine', 'strength training', 'running', 'mobility', 'endurance', 'strength', 'workout', 'knee', 'athlete', 'nutrition'],
    'Life Improvement': ['self-improvement', 'productivity', 'time management', 'management', 'advice', 'self-development'],
    'comedy': ['comedy', 'skit', 'funny', 'fun']

  }

  # Check all categories in order of priority, using whole word matching
  for category_group in [specialized_categories, medium_categories, broad_categories]:
    for category, keywords in category_group.items():
      for kw in keywords:
        # Use regex to match whole words or exact phrases
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, full_text):
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
    quota_tracker = QuotaTracker()
    youtube = get_authenticated_service()

    print("Fetching ALL your subscribed channels...")
    channels = get_all_subscribed_channels(youtube, quota_tracker)
    print(f"Found {len(channels)} subscribed channels.")

    # Categorize and prepare export data
    categorized = {
        'metadata': {
            'total_channels': len(channels),
            'api_quota_used': quota_tracker.get_quota_used(),
            'categories_count': {}
        },
        'channels': {}
    }

    temp_categories = {}
    for channel in channels:
        desc = channel['description'].strip()
        title = channel['title']
        if not desc:
            category = 'no description'
        else:
            category = categorize_channel(desc, title)
            # If miscellaneous, try with title only
            if category == 'miscellaneous':
                category = categorize_channel('', title)
        if category not in temp_categories:
            temp_categories[category] = []
        temp_categories[category].append(channel)

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

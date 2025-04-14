from pathlib import Path
import googleapiclient.discovery
import google_auth_oauthlib.flow
from datetime import datetime, timedelta
import csv
import json
import time
import os
from collections import defaultdict
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from nltk.stem import PorterStemmer  # Added for word stemming
from nltk.corpus import stopwords
from nltk.corpus import wordnet
from nltk.tokenize import word_tokenize
from nltk import pos_tag

# Configuration
CLIENT_SECRETS_FILE = "C:\\Users\\hipra\\Downloads\\client_secret_REDACTED_CLIENT_ID.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
CACHE_FILE = "youtube_search_cache.json"
MAX_RESULTS_PER_CHANNEL = 15  # Increased from 10
MAX_RELEVANT_CHANNELS = 50
SECONDS_BETWEEN_REQUESTS = 0.1
DAYS_BACK = 2000 
TEST_CHANNEL_LIMIT = 1
MIN_DESCRIPTION_LENGTH = 10
MIN_VIEW_COUNT = 300  # Lowered from 500
MAX_DURATION = 18000  # Increased from 10000 (5 hours)

# Output directories
RESULTS_DIR = "youtube_results"
TEST_RESULTS_DIR = "test_results"

# Global setting for keyword regeneration
REGENERATE_KEYWORDS = input("Do you want to regenerate keywords for this run? (y/n): ").strip().lower() == 'y'

def ensure_directories():
    """Create both output directories if they don't exist"""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(TEST_RESULTS_DIR, exist_ok=True)

def get_output_filename(test_mode=False):
    """Generate appropriate output filename based on mode"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if test_mode:
        return os.path.join(TEST_RESULTS_DIR, f"results_{timestamp}.csv")
    return os.path.join(RESULTS_DIR, f"results_{timestamp}.csv")

def authenticate_youtube():
    """Authenticate with YouTube API using OAuth"""
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, SCOPES)
    credentials = flow.run_local_server(port=0)
    return googleapiclient.discovery.build("youtube", "v3", credentials=credentials)

def load_cache():
    """Load cached search results with expiration"""
    try:
        with open(CACHE_FILE, 'r') as f:
            cache = json.load(f)
            cache_date = datetime.fromisoformat(cache.get("cache_date", "2000-01-01")).replace(tzinfo=None)
            if datetime.now() - cache_date > timedelta(days=7):
                return {"searches": {}, "channels": [], "channel_descriptions": {}, "relevance_scores": {}, "cache_date": datetime.now().isoformat()}
            return cache
    except (FileNotFoundError, json.JSONDecodeError):
        return {"searches": {}, "channels": [], "channel_descriptions": {}, "relevance_scores": {}, "cache_date": datetime.now().isoformat()}

def save_cache(cache):
    """Save channel data to cache with timestamp"""
    cache["cache_date"] = datetime.now().isoformat()
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)

def parse_duration(duration_str):
    """Parse ISO 8601 duration string into seconds"""
    try:
        if duration_str == "N/A":
            return 0
        duration_str = duration_str[2:]  # Remove 'PT' prefix
        hours = minutes = seconds = 0

        if 'H' in duration_str:
            hours_part, duration_str = duration_str.split('H', 1)
            hours = int(hours_part)
        if 'M' in duration_str:
            minutes_part, duration_str = duration_str.split('M', 1)
            minutes = int(minutes_part)
        if 'S' in duration_str:
            seconds_part = duration_str.split('S')[0]
            seconds = int(seconds_part)

        return hours * 3600 + minutes * 60 + seconds
    except:
        return 0

def preprocess_text(text):
    """Clean and preprocess text for analysis"""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r'[^\w\s]', '', text)  # Remove punctuation
    text = re.sub(r'\s+', ' ', text).strip()  # Normalize whitespace
    return text

def expand_query_terms(query):
    """Basic query expansion using word stemming"""
    stemmer = PorterStemmer()
    query_terms = query.lower().split()
    expanded_terms = set(query_terms)
    
    # Add stemmed versions of words
    expanded_terms.update([stemmer.stem(word) for word in query_terms])
    
    return list(expanded_terms)

def is_relevant_video(video_info, query_terms):
    """Flexible relevance checking with scoring"""
    title = preprocess_text(video_info["title"])
    description = preprocess_text(video_info["description"])
    
    # Score based on term matches
    title_score = sum(1 for term in query_terms if term in title)
    desc_score = sum(1 for term in query_terms if term in description)
    
    # Consider a video relevant if:
    # - At least 2 terms in title, OR
    # - 1 term in title and 1 in description, OR
    # - 3+ terms in description
    return (title_score >= 2) or (title_score >= 1 and desc_score >= 1) or (desc_score >= 3)

def get_channel_description(youtube, channel_id, cache):
    """Get channel description with caching (1 quota unit)"""
    if channel_id in cache.get("channel_descriptions", {}):
        return cache["channel_descriptions"][channel_id]
    
    try:
        response = youtube.channels().list(
            part="snippet",
            id=channel_id,
            fields="items(snippet(title,description))"
        ).execute()
        
        description = response["items"][0]["snippet"].get("description", "") if response.get("items") else ""
        
        # Cache the description
        if "channel_descriptions" not in cache:
            cache["channel_descriptions"] = {}
        cache["channel_descriptions"][channel_id] = description
        save_cache(cache)

        return metadata

    except Exception as e:
        print(f"Error fetching description for channel {channel_id}: {e}")
        return ""

def calculate_semantic_similarity(query, text):
    """Calculate semantic similarity between query and text using TF-IDF."""
    if not text or len(text) < MIN_DESCRIPTION_LENGTH:
        return 0.0
    
    # Preprocess both query and text
    processed_query = preprocess_text(query)
    processed_text = preprocess_text(text)
    
    # Create TF-IDF vectors
    vectorizer = TfidfVectorizer().fit_transform([processed_query, processed_text])
    vectors = vectorizer.toarray()
    
    # Calculate cosine similarity
    similarity = cosine_similarity(vectors[0:1], vectors[1:2])[0][0]
    # Convert to percentage and truncate to 2 decimal places
    return round(similarity * 100, 2)

def get_channel_relevance_score(youtube, channel, query, cache):
    """Calculate channel relevance score without considering title matches unless the description is blank"""
    try:
        # Get channel metadata (2 quota units)
        response = youtube.channels().list(
            part="snippet,statistics",
            id=channel["id"],
            fields="items(snippet(description,title))"
        ).execute()
        
        channel_data = response["items"][0]
        description = channel_data["snippet"].get("description", "").lower()
        title = channel_data["snippet"].get("title", "").lower()
        
        # Preprocess the query
        processed_query = preprocess_text(query)
        query_terms = expand_query_terms(query)
        
        # 1. Description similarity
        desc_similarity = 0
        if description:
            desc_similarity = calculate_semantic_similarity(query, description) * 100
        
        # 2. Title matches (only if description is blank)
        title_score = 0
        if not description:
            title_matches = [term for term in query_terms if term in title]
            title_score = len(title_matches) * 10  # Assign a score for title matches
        
        # Combined score
        total_score = desc_similarity + title_score
        
        # Return detailed score breakdown
        return {
            "total_score": total_score,
            "description_similarity": desc_similarity,
            "title_matches": title_score > 0,
            "title_score": title_score
        }
        
    except Exception as e:
        print(f"Error scoring channel {channel['title']}: {e}")
        return {
            "total_score": 0,
            "description_similarity": 0,
            "title_matches": False,
            "title_score": 0
        }

def get_most_relevant_channels(youtube, channels, query, cache):
    """Return the top 50 most relevant channels with reasons for relevance"""
    print(f"\nEvaluating relevance for {len(channels)} channels...")

    channel_scores = []
    for channel in channels:
        prelim_channels.append(channel)
    
    # Detailed scoring for preliminary channels
    channel_scores = []
    for channel in prelim_channels:
        score_details = get_channel_relevance_score(youtube, channel, query, cache)
        channel_scores.append((score_details, channel))
        print(f"  {channel['title'][:30]}... Score: {score_details['total_score']:.1f}", end='\r')

    # Sort by score (descending)
    channel_scores.sort(reverse=True, key=lambda x: x[0]["total_score"])
    top_channels = channel_scores[:MAX_RELEVANT_CHANNELS]
    
    print(f"\nSelected top {len(top_channels)} most relevant channels")
    return top_channels

def get_subscribed_channels(youtube, cache, test_mode=False):
    """Get subscribed channels with enhanced caching"""
    if cache.get("channels"):
        print(f"Using {len(cache['channels'])} cached channels")
        return cache["channels"][:TEST_CHANNEL_LIMIT] if test_mode else cache["channels"]

    print("Fetching subscribed channels...")
    channels = []
    next_page_token = None

    while True:
        time.sleep(SECONDS_BETWEEN_REQUESTS * 2)
        try:
            request = youtube.subscriptions().list(
                part="snippet",
                mine=True,
                maxResults=50,
                pageToken=next_page_token
            )
            response = request.execute()

            channels.extend({
                "title": item["snippet"]["title"],
                "id": item["snippet"]["resourceId"]["channelId"]
            } for item in response.get("items", []))

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break

        except Exception as e:
            print(f"Error fetching subscriptions: {e}")
            break

    cache["channels"] = channels
    save_cache(cache)
    return channels[:TEST_CHANNEL_LIMIT] if test_mode else channels

def search_channel_videos(youtube, channel, query, cache, test_mode=False):
    """Improved general video search without query-specific optimizations"""
    channel_id = channel["id"]
    videos = []
    query_terms = expand_query_terms(query)

    try:
        time.sleep(SECONDS_BETWEEN_REQUESTS)

        # First try with exact phrase for precision
        exact_response = youtube.search().list(
            part="snippet",
            channelId=channel_id,
            q=f'"{query}"',  # Exact phrase match
            maxResults=5,
            type="video",
            order="viewCount",  # Most popular first
            fields="items(id(videoId),snippet(title,description,publishedAt))"
        ).execute()

        # Fall back to broader search if few results
        if len(exact_response.get("items", [])) < 3:
            search_response = youtube.search().list(
                part="snippet",
                channelId=channel_id,
                q=query,  # Regular search
                maxResults=MAX_RESULTS_PER_CHANNEL,
                type="video",
                order="viewCount",
                fields="items(id(videoId),snippet(title,description,publishedAt))"
            ).execute()
            items = search_response.get("items", [])
        else:
            items = exact_response.get("items", [])

        video_data = []
        for video in filtered_videos:
            video_info = {
                "id": video["snippet"]["resourceId"]["videoId"],
                "title": video["snippet"]["title"],
                "description": video["snippet"]["description"],
                "published_at": video["snippet"]["publishedAt"]
            }
            if is_relevant_video(video_info, query_terms):
                video_data.append(video_info)

        # Fetch video details (duration, view count)
        video_ids = [v["id"] for v in video_data]
        if not video_ids:
            print(f"No relevant videos found for channel: {channel['title']}")
            return []

        # Process video IDs in batches of 50
        details_map = {}
        for i in range(0, len(video_ids), 50):
            batch_ids = video_ids[i:i + 50]
            try:
                details_response = youtube.videos().list(
                    part="contentDetails,statistics",
                    id=",".join(batch_ids),
                    fields="items(id,contentDetails/duration,statistics(viewCount))"
                ).execute()

                for item in details_response.get("items", []):
                    details_map[item["id"]] = item
            except Exception as e:
                print(f"Error fetching video details for batch: {e}")

        for video in video_data:
            details = details_map.get(video["id"], {})
            view_count = int(details.get("statistics", {}).get("viewCount", 0))
            duration = details.get("contentDetails", {}).get("duration", "PT0M")
            duration_sec = parse_duration(duration)

            if view_count >= MIN_VIEW_COUNT and duration_sec <= MAX_DURATION:
                videos.append({
                    "title": video["title"],
                    "channel": channel["title"],
                    "published_at": video["published_at"],
                    "views": view_count,
                    "duration": duration,
                    "url": f"https://youtube.com/watch?v={video['id']}",
                    "description": video["description"]
                })

        if test_mode and videos:
            print(f"[TEST] Found {len(videos)} relevant videos in {channel['title']}")

        cache["searches"][cache_key] = videos
        save_cache(cache)

    except Exception as e:
        print(f"Error processing {channel['title']}: {e}")

    return videos

def export_to_csv(results, query, test_mode=False):
    """Export results to CSV with proper directory structure"""
    if not results:
        print("[TEST] No results to export" if test_mode else "No results to export")
        return

    filename = get_output_filename(test_mode)

    with open(filename, 'w', newline='', encoding='utf-8') as f:
        f.write(f"# Search Query: {query}\n")
        f.write(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# Mode: {'Test' if test_mode else 'Production'}\n")
        
        writer = csv.DictWriter(f, fieldnames=[
            "title", "channel", "published_at", "views",
            "duration", "url", "description"
        ])
        writer.writeheader()
        writer.writerows(results)

    print(f"\nResults saved to: {filename}")

def run_test_version(youtube, query):
    """Run the test version with top channels and display reasons"""
    cache = load_cache()
    print("\n=== TEST MODE ===")
    print(f"Searching for: '{query}'")
    print(f"Evaluating all channels for relevance, but only searching top {TEST_CHANNEL_LIMIT}\n")

    # Get all channels but only process top most relevant
    all_channels = get_subscribed_channels(youtube, cache)
    relevant_channels = get_most_relevant_channels(youtube, all_channels, query, cache)
    test_channels = relevant_channels[:TEST_CHANNEL_LIMIT]

    results = []
    total_quota = 0

    for i, (score_details, channel) in enumerate(test_channels, 1):
        print(f"Processing {i}/{len(test_channels)}: {channel['title'][:30]}...")
        videos = search_channel_videos(youtube, channel, query, cache, test_mode=True)
        results.extend(videos)
        total_quota += 100 + len(videos)
        print(f"  Found {len(videos)} videos in {channel['title']}")

    results.sort(key=lambda x: x["views"], reverse=True)
    export_to_csv(results, query, test_mode=True)

    print(f"\nTest complete! Top channels analyzed:")
    for i, (score_details, channel) in enumerate(test_channels, 1):
        print(f"{i}. {channel['title']}")
        print(f"   - Total Score: {score_details['total_score']:.1f}")
        print(f"   - Description Similarity: {score_details['description_similarity']:.1f}%")
        print(f"   - Title Matches Considered: {'Yes' if score_details['title_matches'] else 'No'}")
        print(f"   - Title Score: {score_details['title_score']}")
    print(f"Total quota used: ~{total_quota} units")

def main():
    print("YouTube Channel Search Tool")
    print("--------------------------")

    test_mode = input("Run in test mode? (y/n): ").strip().lower() == 'y'
    regenerate_keywords = input("Regenerate and cache channel keywords? (y/n): ").strip().lower() == 'y'
    youtube = authenticate_youtube()

    query = input("\nEnter search query: ").strip()
    while not query:
        query = input("Please enter a valid query: ").strip()

    if test_mode:
        run_test_version(youtube, query)
        return

    cache = load_cache()
    all_channels = get_subscribed_channels(youtube, cache)

    # Get most relevant channels first
    relevant_channels = get_most_relevant_channels(youtube, all_channels, query, cache)
    
    print(f"\nSearching across {len(relevant_channels)} most relevant channels for: '{query}'")
    
    results = []
    total_videos_processed = 0
    total_quota_used = 0

    for i, channel in enumerate(relevant_channels, 1):
        print(f"Processing {i}/{len(relevant_channels)}: {channel['title'][:30]}...", end='\r')
        videos = search_channel_videos(youtube, channel, query, cache)
        results.extend(videos)
        total_quota += 100 + len(videos)

    results.sort(key=lambda x: x["views"], reverse=True)

    # Export results to CSV without limiting the length
    export_to_csv(results, query, test_mode)

    print(f"\nSearch complete! Found {len(results)} videos")
    print(f"Total videos processed: {total_videos_processed}")
    print(f"Total quota used: ~{total_quota_used} units")

def estimate_channel_quota_usage(videos_processed):
    """Estimate the API quota usage for a single channel."""
    # 1 quota unit per 50 videos for playlistItems.list
    playlist_items_quota = (videos_processed + 49) // 50  # Round up

    # 1 quota unit per 50 videos for videos.list
    video_details_quota = (videos_processed + 49) // 50  # Round up

    # 100 quota units for fetching channel metadata (channels.list)
    channel_metadata_quota = 100

    # Total quota usage for this channel
    return playlist_items_quota + video_details_quota + channel_metadata_quota

if __name__ == "__main__":
    ensure_directories()
    main()

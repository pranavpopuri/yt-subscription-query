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
            cache_date = datetime.fromisoformat(
                cache.get("cache_date", "2000-01-01")).replace(tzinfo=None)
            if datetime.now() - cache_date > timedelta(days=7):
                return {
                    "channels": [],
                    "channel_descriptions": {},
                    "relevance_scores": {},
                    "cache_date": datetime.now().isoformat()
                }
            return cache
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "channels": [],
            "channel_descriptions": {},
            "relevance_scores": {},
            "cache_date": datetime.now().isoformat()
        }

    except (FileNotFoundError, json.JSONDecodeError):
        # Return a new cache if the file is missing or corrupted
        return {
            "searches": {},  # Ensure 'searches' key is initialized
            "channels": [],
            "channel_descriptions": {},
            "relevance_scores": {},
            "cache_date": datetime.now().isoformat()
        }

def save_cache(cache):
    """Save search results to cache with timestamp"""
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
    """Flexible relevance checking with relaxed scoring."""
    title = preprocess_text(video_info["title"])
    description = preprocess_text(video_info["description"])

    # Score based on term matches
    title_score = sum(1 for term in query_terms if term in title)
    desc_score = sum(1 for term in query_terms if term in description)

    # Consider a video relevant if:
    # - At least 1 term in the title, OR
    # - At least 2 terms in the description, OR
    # - A combined score of 2 or more across title and description
    return (title_score >= 1) or (desc_score >= 2) or (title_score + desc_score >= 2)

def get_channel_metadata(youtube, channel_id, cache):
    """Fetch and cache channel metadata including name, description, and core topics."""
    if not REGENERATE_KEYWORDS and channel_id in cache.get("channel_metadata", {}):
        return cache["channel_metadata"][channel_id]

    try:
        # Fetch channel metadata
        response = youtube.channels().list(
            part="snippet",
            id=channel_id,
            fields="items(snippet(title,description))"
        ).execute()

        if not response.get("items"):
            return None

        snippet = response["items"][0]["snippet"]
        title = snippet.get("title", "")
        description = snippet.get("description", "")

        # Generate core topics based on the description
        core_topics = generate_inference_based_keywords(description) if description.strip() else []

        # Cache the metadata
        metadata = {
            "title": title,
            "description": description,
            "core_topics": core_topics
        }
        if "channel_metadata" not in cache:
            cache["channel_metadata"] = {}
        cache["channel_metadata"][channel_id] = metadata
        save_cache(cache)

        return metadata

    except Exception as e:
        print(f"Error fetching metadata for channel {channel_id}: {e}")
        return None

def generate_inference_based_keywords(description, n=5):
    """Generate up to n core topics using noun-based NLP techniques."""
    if not description.strip():
        return []

    # Preprocess the description
    processed_description = preprocess_text(description)

    # Tokenize and tag parts of speech
    words = word_tokenize(processed_description)
    tagged_words = pos_tag(words)

    # Extract nouns and noun phrases
    keywords = set()
    for word, tag in tagged_words:
        if tag.startswith("NN"):  # Nouns (NN, NNP, etc.)
            keywords.add(word)

    # Filter out stop words and overly generic terms
    stop_words = set(stopwords.words("english"))
    keywords = {kw for kw in keywords if kw not in stop_words and len(kw) > 2}

    # Rank keywords based on frequency in the description
    keyword_counts = {kw: processed_description.split().count(kw) for kw in keywords}
    ranked_keywords = sorted(keyword_counts, key=keyword_counts.get, reverse=True)

    return ranked_keywords[:n]

def filter_and_rank_keywords(keywords, context):
    """Filter and rank keywords based on their relevance to the context."""
    stop_words = set(stopwords.words("english"))
    context_words = set(context.split())
    ranked_keywords = []

    for keyword in keywords:
        # Skip overly generic terms
        if len(keyword) < 3 or keyword in stop_words:
            continue

        # Score keywords based on their presence in the context
        score = sum(1 for word in keyword.split() if word in context_words)
        ranked_keywords.append((score, keyword))

    # Sort by score and return the keywords
    ranked_keywords.sort(reverse=True, key=lambda x: x[0])
    return [keyword for _, keyword in ranked_keywords]

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

def get_channel_relevance_score(metadata, query):
    """
    Calculate channel relevance score with priorities:
    1. Full-query matches in the description (highest weight)
    2. Single-word/phrase keyword matches in the description (medium weight)
    3. Title matches (lowest weight)
    """
    if not metadata:
        return {
            "total_score": 0,
            "description_full_match": 0,
            "description_keyword_match": 0,
            "title_similarity": 0
        }

    description = metadata["description"]
    title = metadata["title"]
    core_topics = metadata["core_topics"]

    # Preprocess the query
    processed_query = preprocess_text(query)

    # 1. Full-query matches in the description
    description_full_match = calculate_semantic_similarity(query, description)

    # 2. Single-word/phrase keyword matches in the description
    description_keyword_match = sum(1 for keyword in core_topics if keyword in preprocess_text(description)) * 10

    # 3. Title matches
    title_similarity = calculate_semantic_similarity(query, title) if title.strip() else 0

    # Weighted combined score
    total_score = (description_full_match * 0.5) + (description_keyword_match * 0.3) + (title_similarity * 0.2)

    return {
        "total_score": total_score,
        "description_full_match": description_full_match,
        "description_keyword_match": description_keyword_match,
        "title_similarity": title_similarity
    }

def get_most_relevant_channels(youtube, channels, query, cache):
    """Return the top most relevant channels based on description and title matches."""
    print(f"\nEvaluating relevance for {len(channels)} channels...")

    channel_scores = []
    for channel in channels:
        metadata = get_channel_metadata(youtube, channel["id"], cache)
        if not metadata:
            continue

        score_details = get_channel_relevance_score(metadata, query)
        channel_scores.append((score_details, channel))
        print(f"  {channel['title'][:30]}... Score: {score_details['total_score']:.1f}", end='\r')

    # Sort by score (descending)
    channel_scores.sort(reverse=True, key=lambda x: x[0]["total_score"])
    top_channels = channel_scores[:MAX_RELEVANT_CHANNELS]

    return top_channels

def get_subscribed_channels(youtube, cache, test_mode=False):
    """Get subscribed channels and cache their metadata"""
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

def get_uploads_playlist_id(youtube, channel_id):
    """Retrieve the uploads playlist ID for a channel."""
    try:
        response = youtube.channels().list(
            part="contentDetails",
            id=channel_id,
            fields="items(contentDetails(relatedPlaylists(uploads)))"
        ).execute()
        return response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except Exception as e:
        print(f"Error fetching uploads playlist for channel {channel_id}: {e}")
        return None

def get_all_videos_from_playlist(youtube, playlist_id):
    """Retrieve all videos from a playlist."""
    videos = []
    next_page_token = None

    while True:
        try:
            response = youtube.playlistItems().list(
                part="snippet",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page_token,
                fields="items(snippet(resourceId(videoId),title,description,publishedAt)),nextPageToken"
            ).execute()

            videos.extend(response["items"])
            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break
        except Exception as e:
            print(f"Error fetching videos from playlist {playlist_id}: {e}")
            break

    return videos

def filter_videos_by_date(videos, days_back):
    """Filter videos based on the DAYS_BACK limit."""
    time_threshold = datetime.utcnow() - timedelta(days=days_back)
    filtered_videos = [
        video for video in videos
        if datetime.strptime(video["snippet"]["publishedAt"], "%Y-%m-%dT%H:%M:%SZ") > time_threshold
    ]
    return filtered_videos

def search_channel_videos(youtube, channel, query, cache):
    """Retrieve all videos from a channel and return the top 50 relevant ones."""
    channel_id = channel["id"]
    videos = []
    query_terms = expand_query_terms(query)

    try:
        # Get the uploads playlist ID
        uploads_playlist_id = get_uploads_playlist_id(youtube, channel_id)
        if not uploads_playlist_id:
            return []

        # Fetch all videos from the uploads playlist
        all_videos = get_all_videos_from_playlist(youtube, uploads_playlist_id)

        # Filter videos by the date limit
        filtered_videos = filter_videos_by_date(all_videos, DAYS_BACK)

        # Process each video
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

        # Sort videos by view count and limit to top 50
        videos.sort(key=lambda x: x["views"], reverse=True)
        videos = videos[:50]

    except Exception as e:
        print(f"Error processing {channel['title']}: {e}")

    return videos

def estimate_quota_usage(channels, total_videos):
    """Estimate the API quota usage."""
    # 1 quota unit per 50 videos for playlistItems.list
    playlist_items_quota = len(channels) * (total_videos // 50 + 1)

    # 1 quota unit per 50 videos for videos.list
    video_details_quota = total_videos // 50 + 1

    # Total quota usage
    total_quota = playlist_items_quota + video_details_quota
    print(f"Estimated quota usage: {total_quota} units")
    return total_quota

def export_to_csv(results, query, test_mode=False):
    """Export results to a CSV file with minimal necessary data."""
    filename = get_output_filename(test_mode)

    with open(filename, 'w', newline='', encoding='utf-8') as f:
        # Write metadata as comments
        f.write(f"# Search Query: {query}\n")
        f.write(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# Mode: {'Test' if test_mode else 'Production'}\n")

        # Define the required fields
        writer = csv.DictWriter(f, fieldnames=[
            "title", "channel", "published_at", "views", "duration", "url"
        ])
        writer.writeheader()

        # Write only the necessary fields
        for result in results:
            writer.writerow({
                "title": result["title"],
                "channel": result["channel"],
                "published_at": result["published_at"],
                "views": result["views"],
                "duration": result["duration"],
                "url": result["url"]
            })

    print(f"\nResults saved to: {filename}")

def main():
    print("YouTube Channel Search Tool")
    print("--------------------------")

    test_mode = input("Run in test mode? (y/n): ").strip().lower() == 'y'
    youtube = authenticate_youtube()

    query = input("\nEnter search query: ").strip()
    while not query:
        query = input("Please enter a valid query: ").strip()

    cache = load_cache()
    all_channels = get_subscribed_channels(youtube, cache)

    # Get most relevant channels first
    relevant_channels = get_most_relevant_channels(youtube, all_channels, query, cache)

    # Limit to 3 channels in test mode
    if test_mode:
        relevant_channels = relevant_channels[:TEST_CHANNEL_LIMIT]

    print(f"\nProcessing {len(relevant_channels)} most relevant channels for: '{query}'")

    results = []
    total_videos_processed = 0
    total_quota_used = 0

    for i, (score_details, channel) in enumerate(relevant_channels, 1):
        print(f"\nProcessing {i}/{len(relevant_channels)}: {channel['title'][:30]}...")
        print(f"  Core Topics: {score_details.get('core_topics', [])}")
        print(f"  Relevance Score:")
        print(f"    Description Similarity: {score_details['description_full_match']}%")
        print(f"    Keyword Similarity: {score_details['description_keyword_match']}%")
        print(f"    Title Matches: {'True' if score_details['title_similarity'] > 0 else 'False'}")
        print(f"    Total Score: {score_details['total_score']:.1f}")

        channel_videos = search_channel_videos(youtube, channel, query, cache)

        # Limit to 20 videos per channel
        channel_videos = channel_videos[:20]

        # Show how many videos were processed for this channel
        print(f"  Processed {len(channel_videos)} videos from channel: {channel['title']}")

        # Add videos to the results
        results.extend(channel_videos)
        total_videos_processed += len(channel_videos)

        # Calculate quota usage for this channel
        channel_quota_used = estimate_channel_quota_usage(len(channel_videos))
        total_quota_used += channel_quota_used
        print(f"  Quota used for this channel: ~{channel_quota_used} units")

    # Rank videos based on relevance
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

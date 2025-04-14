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
import nltk
from nltk.corpus import wordnet, stopwords
from nltk.tokenize import word_tokenize, sent_tokenize
from nltk.tag import pos_tag
from nltk.stem import WordNetLemmatizer
from nltk.stem import PorterStemmer

# Import from our new modules
from config import (
    CLIENT_SECRETS_FILE, SCOPES, CACHE_FILE, MAX_RESULTS_PER_CHANNEL,
    MAX_RELEVANT_CHANNELS, SECONDS_BETWEEN_REQUESTS, DAYS_BACK,
    TEST_CHANNEL_LIMIT, MIN_DESCRIPTION_LENGTH, MIN_VIEW_COUNT,
    MAX_DURATION, RESULTS_DIR, TEST_RESULTS_DIR
)
from utils import (
    ensure_directories, get_output_filename, parse_duration,
    preprocess_text, expand_query_terms, is_relevant_video,
    export_to_csv
)
from nlp_utils import (
    extract_core_entities, contextual_topic_expansion,
    filter_and_rank_topics, generate_channel_keywords
)

# Initialize NLP resources
nltk.download(['punkt_tab', 'averaged_perceptron_tagger_eng', 'wordnet', 'stopwords'], quiet=True)
lemmatizer = WordNetLemmatizer()
stop_words = set(stopwords.words('english'))

def authenticate_youtube():
    """Authenticate with YouTube API using OAuth"""
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, SCOPES)
    credentials = flow.run_local_server(port=0)
    return googleapiclient.discovery.build("youtube", "v3", credentials=credentials)

def load_cache(regenerate_keywords=False):
    """Load cached channel data with expiration"""
    try:
        with open(CACHE_FILE, 'r') as f:
            cache = json.load(f)
            cache_date = datetime.fromisoformat(cache.get("cache_date", "2000-01-01")).replace(tzinfo=None)
            
            if regenerate_keywords:
                # Clear existing keywords if we want to regenerate them
                if "channel_metadata" in cache:
                    for channel_id in cache["channel_metadata"]:
                        if "keywords" in cache["channel_metadata"][channel_id]:
                            del cache["channel_metadata"][channel_id]["keywords"]
                cache["cache_date"] = datetime.now().isoformat()
                return cache
            
            if datetime.now() - cache_date > timedelta(days=7):
                return {
                    "channels": [],
                    "channel_metadata": {},
                    "cache_date": datetime.now().isoformat()
                }
            return cache
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "channels": [],
            "channel_metadata": {},
            "cache_date": datetime.now().isoformat()
        }

def save_cache(cache):
    """Save channel data to cache with timestamp"""
    cache["cache_date"] = datetime.now().isoformat()
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)

def get_channel_metadata(youtube, channel_id, cache, regenerate_keywords=False):
    """Get or generate enhanced channel metadata with semantic keywords"""
    if channel_id in cache.get("channel_metadata", {}) and not regenerate_keywords:
        return cache["channel_metadata"][channel_id]

    try:
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

        # Generate enhanced keywords only if the description is not blank
        keywords = []
        if description.strip():
            keywords = generate_channel_keywords(title, description)

        metadata = {
            "title": title,
            "description": description,
            "keywords": keywords
        }

        # Cache the metadata
        if "channel_metadata" not in cache:
            cache["channel_metadata"] = {}
        cache["channel_metadata"][channel_id] = metadata
        save_cache(cache)

        return metadata

    except Exception as e:
        print(f"Error fetching metadata for channel {channel_id}: {e}")
        return None

def calculate_semantic_similarity(query, text):
    """Calculate semantic similarity between query and text using TF-IDF"""
    if not text or len(text) < MIN_DESCRIPTION_LENGTH:
        return 0.0
    
    processed_query = preprocess_text(query)
    processed_text = preprocess_text(text)
    
    vectorizer = TfidfVectorizer().fit_transform([processed_query, processed_text])
    vectors = vectorizer.toarray()
    
    similarity = cosine_similarity(vectors[0:1], vectors[1:2])[0][0]
    return similarity

def get_channel_relevance_score(channel_metadata, query):
    """
    Calculate channel relevance score with priorities:
    1. Description matches (highest weight)
    2. Title matches (lower weight)
    """
    if not channel_metadata:
        return {
            "total_score": 0,
            "description_similarity": 0,
            "title_similarity": 0
        }

    description = channel_metadata["description"]
    title = channel_metadata["title"]

    if not description.strip():
        # If description is blank, use the title and give it full weight
        desc_similarity = 0
        title_similarity = calculate_semantic_similarity(query, title) * 100
        total_score = title_similarity
    else:
        # Description similarity (70% weight)
        desc_similarity = calculate_semantic_similarity(query, description) * 100
        # Title similarity (30% weight)
        title_similarity = calculate_semantic_similarity(query, title) * 100
        total_score = (desc_similarity * 0.7) + (title_similarity * 0.3)

    return {
        "total_score": total_score,
        "description_similarity": desc_similarity,
        "title_similarity": title_similarity
    }

def get_most_relevant_channels(youtube, channels, query, cache, regenerate_keywords=False):
    """Return the top most relevant channels using cached metadata"""
    print(f"\nEvaluating relevance for {len(channels)} channels...")

    channel_scores = []
    for channel in channels:
        metadata = get_channel_metadata(youtube, channel["id"], cache, regenerate_keywords)
        if not metadata:
            continue

        score_details = get_channel_relevance_score(metadata, query)
        channel_scores.append((score_details, channel))
        print(f"  {channel['title'][:30]}... Score: {score_details['total_score']:.1f}", end='\r')

    # Sort by score (descending)
    channel_scores.sort(reverse=True, key=lambda x: x[0]["total_score"])
    top_channels = channel_scores[:MAX_RELEVANT_CHANNELS]

    print(f"\nSelected top {len(top_channels)} most relevant channels")
    return top_channels

def get_subscribed_channels(youtube, cache, test_mode=False):
    """Get subscribed channels with caching"""
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

def search_channel_videos(youtube, channel, query, test_mode=False):
    """Search for videos in a channel without caching results"""
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
            order="viewCount",
            fields="items(id(videoId),snippet(title,description,publishedAt))"
        ).execute()

        # Fall back to broader search if few results
        if len(exact_response.get("items", [])) < 3:
            search_response = youtube.search().list(
                part="snippet",
                channelId=channel_id,
                q=query,
                maxResults=MAX_RESULTS_PER_CHANNEL,
                type="video",
                order="viewCount",
                fields="items(id(videoId),snippet(title,description,publishedAt))"
            ).execute()
            items = search_response.get("items", [])
        else:
            items = exact_response.get("items", [])

        video_data = []
        for item in items:
            video_info = {
                "id": item["id"]["videoId"],
                "title": item["snippet"]["title"],
                "description": item["snippet"]["description"],
                "published_at": item["snippet"]["publishedAt"]
            }
            if is_relevant_video(video_info, query_terms):
                video_data.append(video_info)

        if not video_data:
            if test_mode:
                print(f"[TEST] No relevant videos found in {channel['title']}")
            return []

        # Get video details (1 quota unit for up to 50 videos)
        video_ids = [v["id"] for v in video_data]
        details_response = youtube.videos().list(
            part="contentDetails,statistics",
            id=",".join(video_ids),
            fields="items(id,contentDetails/duration,statistics/viewCount)"
        ).execute()

        details_map = {item["id"]: item for item in details_response.get("items", [])}

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

    except Exception as e:
        print(f"Error processing {channel['title']}: {e}")

    return videos

def run_test_version(youtube, query, regenerate_keywords=False):
    """Run the test version with enhanced keyword display"""
    cache = load_cache(regenerate_keywords)
    print("\n=== TEST MODE ===")
    print(f"Searching for: '{query}'")
    print(f"Evaluating all channels for relevance, but only searching top {TEST_CHANNEL_LIMIT}\n")

    all_channels = get_subscribed_channels(youtube, cache)
    relevant_channels = get_most_relevant_channels(youtube, all_channels, query, cache, regenerate_keywords)
    test_channels = relevant_channels[:TEST_CHANNEL_LIMIT]

    results = []
    total_quota = 0

    for i, (score_details, channel) in enumerate(test_channels, 1):
        print(f"Processing {i}/{len(test_channels)}: {channel['title'][:30]}...")
        videos = search_channel_videos(youtube, channel, query, test_mode=True)
        results.extend(videos)
        total_quota += 100 + len(videos)
        print(f"  Found {len(videos)} videos in {channel['title']}")

    results.sort(key=lambda x: x["views"], reverse=True)
    export_to_csv(results, query, test_mode=True)

    print(f"\nTest complete! Top channels analyzed:")
    for i, (score_details, channel) in enumerate(test_channels, 1):
        metadata = cache["channel_metadata"].get(channel["id"], {})
        print(f"\n{i}. {channel['title']}")
        print(f"   - Total Score: {score_details['total_score']:.1f}")
        print(f"   - Description Similarity: {score_details['description_similarity']:.1f}%")
        print(f"   - Title Similarity: {score_details['title_similarity']:.1f}%")
        if metadata.get('keywords'):
            print(f"   - Generated Keywords:")
            for j, keyword in enumerate(metadata['keywords'], 1):
                print(f"      {j}. {keyword}")
    print(f"\nTotal quota used: ~{total_quota} units")

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
        run_test_version(youtube, query, regenerate_keywords)
        return

    cache = load_cache(regenerate_keywords)
    all_channels = get_subscribed_channels(youtube, cache)
    
    # Get most relevant channels first
    relevant_channels = get_most_relevant_channels(youtube, all_channels, query, cache, regenerate_keywords)
    
    print(f"\nSearching across {len(relevant_channels)} most relevant channels for: '{query}'")
    
    results = []
    total_quota = 0

    for i, (_, channel) in enumerate(relevant_channels, 1):
        print(f"Processing {i}/{len(relevant_channels)}: {channel['title'][:30]}...", end='\r')
        videos = search_channel_videos(youtube, channel, query)
        results.extend(videos)
        total_quota += 100 + len(videos)

    results.sort(key=lambda x: x["views"], reverse=True)
    export_to_csv(results, query)

    print(f"\nSearch complete! Found {len(results)} videos")
    print(f"Total quota used: ~{total_quota} units (max 50 channels * ~125 = 6,250 units)")

if __name__ == "__main__":
    ensure_directories()
    main()

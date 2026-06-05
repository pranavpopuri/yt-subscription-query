from datetime import datetime, timedelta
import csv
import math
import time
import os
import re
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
from sklearn.metrics.pairwise import cosine_similarity
from nltk.stem import PorterStemmer
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
from nltk import pos_tag

_stemmer = PorterStemmer()

def _stem_tokenize(text):
    tokens = re.findall(r'[a-z]+', text.lower())
    return [_stemmer.stem(t) for t in tokens if t not in ENGLISH_STOP_WORDS]


MAX_RELEVANT_CHANNELS = 50
SECONDS_BETWEEN_REQUESTS = 0.1
DAYS_BACK = 365
TEST_CHANNEL_LIMIT = 2
MIN_DESCRIPTION_LENGTH = 10
MIN_VIEW_COUNT = 300
MIN_DURATION = 60
MAX_DURATION = 18000

RESULTS_DIR = "youtube_results"
TEST_RESULTS_DIR = "test_results"


def ensure_directories():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    os.makedirs(TEST_RESULTS_DIR, exist_ok=True)


def get_output_filename(test_mode=False):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if test_mode:
        return os.path.join(TEST_RESULTS_DIR, f"results_{timestamp}.csv")
    return os.path.join(RESULTS_DIR, f"results_{timestamp}.csv")


def parse_duration(duration_str):
    try:
        if duration_str == "N/A":
            return 0
        duration_str = duration_str[2:]
        hours = minutes = seconds = 0
        if 'H' in duration_str:
            hours_part, duration_str = duration_str.split('H', 1)
            hours = int(hours_part)
        if 'M' in duration_str:
            minutes_part, duration_str = duration_str.split('M', 1)
            minutes = int(minutes_part)
        if 'S' in duration_str:
            seconds = int(duration_str.split('S')[0])
        return hours * 3600 + minutes * 60 + seconds
    except (ValueError, AttributeError):
        return 0


def preprocess_text(text):
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def expand_query_terms(query):
    stemmer = PorterStemmer()
    query_terms = query.lower().split()
    expanded_terms = set(query_terms)
    expanded_terms.update([stemmer.stem(word) for word in query_terms])
    return list(expanded_terms)


def is_relevant_video(video_info, query_terms):
    title = preprocess_text(video_info["title"])
    description = preprocess_text(video_info["description"])
    title_score = sum(1 for term in query_terms if re.search(rf'\b{re.escape(term)}\b', title))
    desc_score = sum(1 for term in query_terms if re.search(rf'\b{re.escape(term)}\b', description))
    return (title_score >= 1) or (desc_score >= 2)


def get_channel_metadata(youtube, channel_id, channel_metadata):
    """Return channel metadata, fetching from API on first access per channel."""
    if channel_id in channel_metadata:
        return channel_metadata[channel_id]
    try:
        response = youtube.channels().list(
            part="snippet", id=channel_id,
            fields="items(snippet(title,description))"
        ).execute()
        if not response.get("items"):
            return None
        snippet = response["items"][0]["snippet"]
        title = snippet.get("title", "")
        description = snippet.get("description", "")
        core_topics = generate_inference_based_keywords(description) if description.strip() else []
        metadata = {"title": title, "description": description, "core_topics": core_topics}
        channel_metadata[channel_id] = metadata
        return metadata
    except Exception as e:
        print(f"Error fetching metadata for channel {channel_id}: {e}")
        return None


def generate_inference_based_keywords(description, n=5):
    if not description.strip():
        return []
    processed_description = preprocess_text(description)
    words = word_tokenize(processed_description)
    tagged_words = pos_tag(words)
    keywords = set()
    for word, tag in tagged_words:
        if tag.startswith("NN"):
            keywords.add(word)
    stop_words = set(stopwords.words("english"))
    keywords = {kw for kw in keywords if kw not in stop_words and len(kw) > 2}
    keyword_counts = {kw: processed_description.split().count(kw) for kw in keywords}
    ranked_keywords = sorted(keyword_counts, key=keyword_counts.get, reverse=True)
    return ranked_keywords[:n]


def calculate_semantic_similarity(query, text):
    if not text or len(text) < MIN_DESCRIPTION_LENGTH:
        return 0.0
    processed_query = preprocess_text(query)
    processed_text = preprocess_text(text)
    vectorizer = TfidfVectorizer().fit_transform([processed_query, processed_text])
    vectors = vectorizer.toarray()
    similarity = cosine_similarity(vectors[0:1], vectors[1:2])[0][0]
    return round(similarity * 100, 2)


def get_channel_relevance_score(metadata, query, weights, playlist_titles=None):
    if not metadata:
        return {
            "total_score": 0,
            "description_full_match": 0,
            "description_keyword_match": 0,
            "title_similarity": 0,
            "playlist_match": 0,
        }

    description = metadata["description"]
    title = metadata["title"]
    core_topics = metadata["core_topics"]

    description_full_match = calculate_semantic_similarity(query, description) if description.strip() else 0

    processed_query = preprocess_text(query)
    description_keyword_match = (
        sum(1 for kw in core_topics if re.search(rf'\b{re.escape(kw)}\b', processed_query)) * 10
        if description.strip() else 0
    )

    title_similarity = (
        calculate_semantic_similarity(query, title)
        if not description.strip() and title.strip() else 0
    )

    playlist_text = " ".join(playlist_titles) if playlist_titles else ""
    playlist_match = calculate_semantic_similarity(query, playlist_text) if playlist_text.strip() else 0

    total_score = (
        (description_full_match      * weights["description_weight"]) +
        (description_keyword_match   * weights["keyword_weight"]) +
        (title_similarity            * weights["title_weight"]) +
        (playlist_match              * weights.get("playlist_weight", 0.5))
    )

    return {
        "total_score": total_score,
        "description_full_match": description_full_match,
        "description_keyword_match": description_keyword_match,
        "title_similarity": title_similarity,
        "playlist_match": playlist_match,
    }


def get_most_relevant_channels(youtube, channels, query, channel_metadata, playlist_names, weights):
    print(f"\nEvaluating relevance for {len(channels)} channels...")
    channel_scores = []
    for channel in channels:
        metadata = get_channel_metadata(youtube, channel["id"], channel_metadata)
        if not metadata:
            continue
        playlist_titles = get_channel_playlists(youtube, channel["id"], playlist_names)
        score_details = get_channel_relevance_score(metadata, query, weights, playlist_titles)
        channel_scores.append((score_details, channel))
        print(f"  {channel['title'][:30]}... Score: {score_details['total_score']:.1f}", end='\r')
    channel_scores.sort(reverse=True, key=lambda x: x[0]["total_score"])
    return channel_scores[:MAX_RELEVANT_CHANNELS]


def get_subscribed_channels(youtube, subscriptions):
    """Return subscribed channels, using the cache if populated."""
    cached = subscriptions.get("channels", [])
    if cached:
        print(f"Using {len(cached)} cached channels")
        return cached
    print("Fetching subscribed channels...")
    channels = []
    next_page_token = None
    while True:
        time.sleep(SECONDS_BETWEEN_REQUESTS * 2)
        try:
            response = youtube.subscriptions().list(
                part="snippet", mine=True, maxResults=50, pageToken=next_page_token
            ).execute()
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
    subscriptions["channels"] = channels
    return channels


def get_uploads_playlist_id(youtube, channel_id):
    try:
        response = youtube.channels().list(
            part="contentDetails", id=channel_id,
            fields="items(contentDetails(relatedPlaylists(uploads)))"
        ).execute()
        return response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except Exception as e:
        print(f"Error fetching uploads playlist for channel {channel_id}: {e}")
        return None


def get_channel_playlists(youtube, channel_id, playlist_names):
    """Return playlist titles for a channel, fetching from API on first access."""
    if channel_id in playlist_names:
        return playlist_names[channel_id]
    titles = []
    next_page_token = None
    try:
        while True:
            response = youtube.playlists().list(
                part="snippet", channelId=channel_id, maxResults=50,
                pageToken=next_page_token, fields="items(snippet/title),nextPageToken"
            ).execute()
            titles.extend(item["snippet"]["title"] for item in response.get("items", []))
            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break
    except Exception as e:
        print(f"Error fetching playlists for channel {channel_id}: {e}")
    playlist_names[channel_id] = titles
    return titles


def fetch_channel_playlists_with_ids(youtube, channel_id):
    """Fetch all playlists for a channel, returning [{id, title}]."""
    playlists = []
    next_page_token = None
    try:
        while True:
            response = youtube.playlists().list(
                part="snippet", channelId=channel_id, maxResults=50,
                pageToken=next_page_token,
                fields="items(id,snippet/title),nextPageToken"
            ).execute()
            for item in response.get("items", []):
                playlists.append({"id": item["id"], "title": item["snippet"]["title"]})
            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break
    except Exception as e:
        print(f"Error fetching playlists for channel {channel_id}: {e}")
    return playlists


def get_video_sample_text(youtube, channel_id, video_samples, n=5):
    """Return sample text from recent videos, fetching from API on first access."""
    if channel_id in video_samples:
        return video_samples[channel_id]
    try:
        playlist_id = get_uploads_playlist_id(youtube, channel_id)
        if not playlist_id:
            video_samples[channel_id] = ""
            return ""
        response = youtube.playlistItems().list(
            part="snippet", playlistId=playlist_id, maxResults=n,
            fields="items(snippet(title,description))"
        ).execute()
        parts = []
        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            parts.append(snippet.get("title", ""))
            parts.append(snippet.get("description", ""))
        text = " ".join(filter(None, parts))
        video_samples[channel_id] = text
        return text
    except Exception as e:
        print(f"Error sampling videos for channel {channel_id}: {e}")
        video_samples[channel_id] = ""
        return ""


def get_all_videos_from_playlist(youtube, playlist_id):
    videos = []
    next_page_token = None
    while True:
        try:
            response = youtube.playlistItems().list(
                part="snippet", playlistId=playlist_id, maxResults=50,
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
    time_threshold = datetime.utcnow() - timedelta(days=days_back)
    return [
        v for v in videos
        if datetime.strptime(v["snippet"]["publishedAt"], "%Y-%m-%dT%H:%M:%SZ") > time_threshold
    ]


def search_channel_videos(youtube, channel, query):
    channel_id = channel["id"]
    videos = []
    query_terms = expand_query_terms(query)
    try:
        uploads_playlist_id = get_uploads_playlist_id(youtube, channel_id)
        if not uploads_playlist_id:
            return []
        all_videos = get_all_videos_from_playlist(youtube, uploads_playlist_id)
        filtered_videos = filter_videos_by_date(all_videos, DAYS_BACK)
        video_data = []
        for video in filtered_videos:
            video_info = {
                "id": video["snippet"]["resourceId"]["videoId"],
                "title": video["snippet"]["title"],
                "description": video["snippet"]["description"],
                "published_at": video["snippet"]["publishedAt"],
            }
            if is_relevant_video(video_info, query_terms):
                video_data.append(video_info)
        video_ids = [v["id"] for v in video_data]
        if not video_ids:
            return []
        details_map = {}
        for i in range(0, len(video_ids), 50):
            batch_ids = video_ids[i:i + 50]
            try:
                details_response = youtube.videos().list(
                    part="contentDetails,statistics", id=",".join(batch_ids),
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
            if view_count >= MIN_VIEW_COUNT and MIN_DURATION <= duration_sec <= MAX_DURATION:
                videos.append({
                    "title": video["title"],
                    "channel": channel["title"],
                    "published_at": video["published_at"],
                    "views": view_count,
                    "duration": duration,
                    "url": f"https://youtube.com/watch?v={video['id']}",
                    "description": video["description"],
                })
        videos.sort(key=lambda x: x["views"], reverse=True)
        return videos[:50]
    except Exception as e:
        print(f"Error processing {channel['title']}: {e}")
        return []


def fetch_channel_videos(youtube, channel_id, max_videos=200):
    """Fetch up to max_videos recent video titles for a channel.

    Returns list of {id, title, published_at} dicts.
    Quota: 1 unit (channels.list) + ceil(max_videos/50) units (playlistItems.list).
    """
    playlist_id = get_uploads_playlist_id(youtube, channel_id)
    if not playlist_id:
        return []
    videos = []
    next_page_token = None
    while len(videos) < max_videos:
        try:
            response = youtube.playlistItems().list(
                part="snippet",
                playlistId=playlist_id,
                maxResults=min(50, max_videos - len(videos)),
                pageToken=next_page_token,
                fields="items(snippet(resourceId/videoId,title,publishedAt)),nextPageToken",
            ).execute()
            for item in response.get("items", []):
                snippet = item["snippet"]
                videos.append({
                    "id": snippet["resourceId"]["videoId"],
                    "title": snippet.get("title", ""),
                    "published_at": snippet.get("publishedAt", ""),
                })
            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break
        except Exception as e:
            print(f"Error fetching videos for channel {channel_id}: {e}")
            break
    return videos


def get_new_channel_videos(youtube, channel_id, since_iso):
    """Fetch videos published strictly after since_iso (ISO 8601 string).

    Returns list of {id, title, published_at} dicts, newest first.
    Stops as soon as a video older than since_iso is encountered.
    Quota: 1 unit (channels.list) + pages until cutoff is reached.
    """
    playlist_id = get_uploads_playlist_id(youtube, channel_id)
    if not playlist_id:
        return []
    videos = []
    next_page_token = None
    while True:
        try:
            response = youtube.playlistItems().list(
                part="snippet",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page_token,
                fields="items(snippet(resourceId/videoId,title,publishedAt)),nextPageToken",
            ).execute()
            done = False
            for item in response.get("items", []):
                snippet = item["snippet"]
                pub = snippet.get("publishedAt", "")
                if pub <= since_iso:
                    done = True
                    break
                videos.append({
                    "id": snippet["resourceId"]["videoId"],
                    "title": snippet.get("title", ""),
                    "published_at": pub,
                })
            next_page_token = response.get("nextPageToken")
            if done or not next_page_token:
                break
        except Exception as e:
            print(f"Error fetching new videos for channel {channel_id}: {e}")
            break
    return videos


def search_with_index(query, video_index, youtube):
    """Search cached video titles with TF-IDF, then rank top results by views.

    Costs ~2 quota units (videos.list for top 100 candidates) regardless of index size.
    Returns list of result dicts in the same shape as search_channel_videos.
    """
    entries = []
    for channel_id, data in video_index.items():
        channel_title = data.get("channel_title", channel_id)
        for v in data.get("videos", []):
            entries.append((channel_title, v))

    if not entries:
        return []

    titles = [e[1]["title"] for e in entries]
    try:
        vectorizer = TfidfVectorizer(analyzer=_stem_tokenize, ngram_range=(1, 2))
        tfidf = vectorizer.fit_transform([query] + titles)
        scores = cosine_similarity(tfidf[0:1], tfidf[1:])[0]
    except Exception:
        return []

    top_indices = scores.argsort()[-100:][::-1]
    candidates = [(scores[i], entries[i]) for i in top_indices if scores[i] > 0]
    if not candidates:
        return []

    video_ids = [c[1][1]["id"] for c in candidates]
    views_map = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        try:
            resp = youtube.videos().list(
                part="statistics",
                id=",".join(batch),
                fields="items(id,statistics/viewCount)",
            ).execute()
            for item in resp.get("items", []):
                views_map[item["id"]] = int(item.get("statistics", {}).get("viewCount", 0))
        except Exception as e:
            print(f"Error fetching view counts: {e}")

    results = []
    for rel_score, (channel_title, video) in candidates:
        vid_id = video["id"]
        views = views_map.get(vid_id, 0)
        combined = rel_score * math.log10(max(views, 10))
        results.append({
            "title": video["title"],
            "channel": channel_title,
            "published_at": video.get("published_at", ""),
            "views": views,
            "duration": "N/A",
            "url": f"https://youtube.com/watch?v={vid_id}",
            "description": "",
            "_score": combined,
        })

    results.sort(key=lambda x: x["_score"], reverse=True)
    for r in results:
        del r["_score"]
    return results


def search_playlists_with_index(query, playlist_index):
    """Search cached playlist titles with TF-IDF.

    Zero quota cost. Returns list of {title, channel, url} dicts.
    """
    entries = []
    for channel_id, data in playlist_index.items():
        channel_title = data.get("channel_title", channel_id)
        for p in data.get("playlists", []):
            entries.append((channel_title, p))

    if not entries:
        return []

    titles = [e[1]["title"] for e in entries]
    try:
        vectorizer = TfidfVectorizer(analyzer=_stem_tokenize, ngram_range=(1, 2))
        tfidf = vectorizer.fit_transform([query] + titles)
        scores = cosine_similarity(tfidf[0:1], tfidf[1:])[0]
    except Exception:
        return []

    results = []
    for i, score in enumerate(scores):
        if score > 0:
            channel_title, playlist = entries[i]
            results.append({
                "title": playlist["title"],
                "channel": channel_title,
                "url": f"https://www.youtube.com/playlist?list={playlist['id']}",
                "_score": score,
            })

    results.sort(key=lambda x: x["_score"], reverse=True)
    for r in results:
        del r["_score"]
    return results[:50]


def export_to_csv(results, query, test_mode=False):
    filename = get_output_filename(test_mode)
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        f.write(f"# Search Query: {query}\n")
        f.write(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# Mode: {'Test' if test_mode else 'Production'}\n")
        writer = csv.DictWriter(f, fieldnames=["title", "channel", "published_at", "views", "duration", "url"])
        writer.writeheader()
        for result in results:
            writer.writerow({k: result[k] for k in ["title", "channel", "published_at", "views", "duration", "url"]})
    print(f"\nResults saved to: {filename}")


def get_user_weights():
    print("\nSet the weights for relevance scoring:")
    while True:
        try:
            dw = float(input("Description weight (e.g., 1.0): ").strip())
            kw = float(input("Keyword weight (e.g., 0.25): ").strip())
            tw = float(input("Title weight (e.g., 0.1): ").strip())
            pw = float(input("Playlist weight (e.g., 0.5): ").strip())
            if any(w < 0 for w in [dw, kw, tw, pw]):
                print("Weights must be non-negative.")
                continue
            return {"description_weight": dw, "keyword_weight": kw, "title_weight": tw, "playlist_weight": pw}
        except ValueError:
            print("Invalid input. Please enter numeric values.")


def estimate_channel_quota_usage(videos_processed):
    playlist_items_quota = (videos_processed + 49) // 50
    video_details_quota = (videos_processed + 49) // 50
    return playlist_items_quota + video_details_quota + 1  # +1 for channels.list


def main():
    import auth
    import cache as cache_mod

    print("YouTube Channel Search Tool")
    print("--------------------------")
    test_mode = input("Run in test mode? (y/n): ").strip().lower() == 'y'
    youtube = auth.build_youtube()
    query = input("\nEnter search query: ").strip()
    while not query:
        query = input("Please enter a valid query: ").strip()
    weights = get_user_weights()

    subscriptions   = cache_mod.load_subscriptions()
    channel_metadata = cache_mod.load_channel_metadata()
    playlist_names  = cache_mod.load_playlist_names()

    all_channels = get_subscribed_channels(youtube, subscriptions)
    relevant_channels = get_most_relevant_channels(
        youtube, all_channels, query, channel_metadata, playlist_names, weights
    )
    if test_mode:
        relevant_channels = relevant_channels[:TEST_CHANNEL_LIMIT]

    print(f"\nProcessing {len(relevant_channels)} most relevant channels for: '{query}'")
    results = []
    total_quota_used = 0
    for i, (score_details, channel) in enumerate(relevant_channels, 1):
        print(f"\nProcessing {i}/{len(relevant_channels)}: {channel['title'][:30]}...")
        print(f"  Description Similarity : {score_details['description_full_match']}%")
        print(f"  Keyword Match          : {score_details['description_keyword_match']}%")
        print(f"  Playlist Match         : {score_details['playlist_match']}%")
        print(f"  Total Score            : {score_details['total_score']:.1f}")
        videos = search_channel_videos(youtube, channel, query)[:20]
        results.extend(videos)
        total_quota_used += estimate_channel_quota_usage(len(videos))

    cache_mod.save_subscriptions(subscriptions.get("channels", []))
    cache_mod.save_channel_metadata(channel_metadata)
    cache_mod.save_playlist_names(playlist_names)

    results.sort(key=lambda x: x["views"], reverse=True)
    export_to_csv(results, query, test_mode)
    print(f"\nSearch complete! Found {len(results)} videos")
    print(f"Total quota used: ~{total_quota_used} units")


if __name__ == "__main__":
    ensure_directories()
    main()

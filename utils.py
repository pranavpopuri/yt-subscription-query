import os
from datetime import datetime
import csv
import re
from nltk.stem import PorterStemmer
from config import RESULTS_DIR, TEST_RESULTS_DIR  # Add this import

stemmer = PorterStemmer()  # Added for expand_query_terms


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
    query_terms = query.lower().split()
    expanded_terms = set(query_terms)

    # Add stemmed versions of words
    expanded_terms.update([stemmer.stem(word) for word in query_terms])

    return list(expanded_terms)


def is_relevant_video(video_info, query_terms):
    """Check if video is relevant to query terms"""
    title = preprocess_text(video_info["title"])
    description = preprocess_text(video_info["description"])

    title_score = sum(1 for term in query_terms if term in title)
    desc_score = sum(1 for term in query_terms if term in description)

    return (title_score >= 2) or (title_score >= 1 and desc_score >= 1) or (desc_score >= 3)


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

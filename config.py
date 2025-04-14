# Configuration
CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
CACHE_FILE = "youtube_channel_cache.json"
MAX_RESULTS_PER_CHANNEL = 15
MAX_RELEVANT_CHANNELS = 50
SECONDS_BETWEEN_REQUESTS = 0.1
DAYS_BACK = 1827  # ~5 years
TEST_CHANNEL_LIMIT = 3
MIN_DESCRIPTION_LENGTH = 10
MIN_VIEW_COUNT = 300
MAX_DURATION = 18000  # 5 hours

# Output directories
RESULTS_DIR = "youtube_results"
TEST_RESULTS_DIR = "test_results"

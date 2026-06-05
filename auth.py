import glob
import os
import googleapiclient.discovery
import google_auth_oauthlib.flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/youtube"]
_TOKEN_FILE = "token.json"


def _secrets_file():
    matches = glob.glob("client_secret*.json")
    if not matches:
        raise FileNotFoundError(
            "No client_secret*.json found. See README for setup instructions."
        )
    return matches[0]


def _build(creds):
    return googleapiclient.discovery.build("youtube", "v3", credentials=creds)


def try_cached_auth():
    """Return a YouTube client using the cached token if valid, else None."""
    if not os.path.exists(_TOKEN_FILE):
        return None
    try:
        creds = Credentials.from_authorized_user_file(_TOKEN_FILE, SCOPES)
        if creds.valid:
            return _build(creds)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(_TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
            return _build(creds)
    except Exception:
        pass
    return None


def build_youtube(force_reauth=False):
    """Return an authenticated YouTube client, opening a browser if needed."""
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    if not force_reauth:
        client = try_cached_auth()
        if client:
            return client

    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
        _secrets_file(), SCOPES
    )
    creds = flow.run_local_server(port=0)
    with open(_TOKEN_FILE, "w") as f:
        f.write(creds.to_json())
    return _build(creds)

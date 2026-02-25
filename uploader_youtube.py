"""
Dark Mind — YouTube Shorts Auto-Uploader
Uses YouTube Data API v3 with OAuth 2.0.

One-time setup:
  1. Go to https://console.cloud.google.com/
  2. Create a project → Enable "YouTube Data API v3"
  3. Credentials → Create OAuth 2.0 Client ID (Desktop app)
  4. Download JSON → save as  client_secrets.json  in this folder
  5. First run opens a browser tab → log in → token.json is saved automatically
  6. All future runs are fully automatic (token auto-refreshes)
"""
import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR       = Path(__file__).parent
CLIENT_SECRETS = BASE_DIR / "client_secrets.json"
TOKEN_FILE     = BASE_DIR / "token.json"
SCOPES         = ["https://www.googleapis.com/auth/youtube.upload",
                  "https://www.googleapis.com/auth/youtube.readonly"]

HASHTAGS_BY_FORMAT = {
    "story_lesson":      "#Shorts #Psychology #DarkPsychology #Mindset #LifeLessons",
    "scary_truth":       "#Shorts #ScaryFacts #DarkTruth #Mystery #DidYouKnow",
    "hidden_psychology": "#Shorts #Psychology #Manipulation #Influence #DarkPsychology",
}


# ============================================================
# AUTH
# ============================================================
def _ensure_client_secrets():
    """
    If client_secrets.json doesn't exist, build it from env vars
    YOUTUBE_OAUTH_CLIENT_ID + YOUTUBE_OAUTH_CLIENT_SECRET.
    """
    if CLIENT_SECRETS.exists():
        return
    client_id     = os.getenv("YOUTUBE_OAUTH_CLIENT_ID", "")
    client_secret = os.getenv("YOUTUBE_OAUTH_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise FileNotFoundError(
            "client_secrets.json not found and env vars missing.\n"
            "Set YOUTUBE_OAUTH_CLIENT_ID and YOUTUBE_OAUTH_CLIENT_SECRET in .env,\n"
            "or download client_secrets.json from Google Cloud Console."
        )
    secrets = {
        "installed": {
            "client_id":                  client_id,
            "client_secret":              client_secret,
            "auth_uri":                   "https://accounts.google.com/o/oauth2/auth",
            "token_uri":                  "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris":              ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        }
    }
    CLIENT_SECRETS.write_text(json.dumps(secrets))
    print("  [YouTube] client_secrets.json created from env vars ✓")


def _get_service():
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        print("  [YouTube] Installing google-api libs…")
        os.system(f"{sys.executable} -m pip install google-api-python-client google-auth-oauthlib -q")
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

    _ensure_client_secrets()

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())

    return build("youtube", "v3", credentials=creds)


# ============================================================
# METADATA
# ============================================================
def _build_title(script_data):
    hook  = script_data.get("hook_text", "").strip()
    topic = script_data.get("topic", "").strip()
    title = hook if hook else topic
    # YouTube indexes vertical short-form as Shorts when title contains #Shorts
    if "#shorts" not in title.lower():
        title = title + " #Shorts"
    return title[:100]


def _build_description(script_data):
    fmt     = script_data.get("format", "story_lesson")
    topic   = script_data.get("topic", "")
    rewatch = script_data.get("rewatch_trigger", "")
    tags    = HASHTAGS_BY_FORMAT.get(fmt, HASHTAGS_BY_FORMAT["story_lesson"])
    parts   = [
        topic,
        "",
        rewatch or "Follow for daily dark psychology content.",
        "",
        tags,
    ]
    return "\n".join(parts)


def _build_tags(script_data):
    fmt = script_data.get("format", "story_lesson")
    base = ["darkpsychology", "psychology", "shorts", "viral", "facts"]
    fmt_tags = {
        "story_lesson":      ["mindset", "motivation", "lifelessons", "business"],
        "scary_truth":       ["scaryfacts", "mystery", "horror", "darktruth"],
        "hidden_psychology": ["manipulation", "influence", "mindcontrol", "body language"],
    }
    return base + fmt_tags.get(fmt, [])


# ============================================================
# UPLOAD
# ============================================================
def upload_to_youtube(video_path, script_data):
    """
    Upload video to YouTube as a Short.
    Returns video_id (str) on success, None on failure.
    """
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        os.system(f"{sys.executable} -m pip install google-api-python-client -q")
        from googleapiclient.http import MediaFileUpload

    try:
        yt = _get_service()

        body = {
            "snippet": {
                "title":       _build_title(script_data),
                "description": _build_description(script_data),
                "tags":        _build_tags(script_data),
                "categoryId":  "22",   # People & Blogs
            },
            "status": {
                "privacyStatus":           "public",
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            resumable=True,
            chunksize=8 * 1024 * 1024,   # 8 MB chunks
        )

        print(f"  [YouTube] Uploading '{Path(video_path).name}'…")
        req      = yt.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None

        while response is None:
            status, response = req.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                print(f"  [YouTube] {pct}%", end="\r")

        video_id = response["id"]
        url      = f"https://youtube.com/shorts/{video_id}"
        print(f"\n  ✅ [YouTube] Published → {url}")
        return video_id

    except Exception as e:
        print(f"\n  ❌ [YouTube] Upload failed: {e}")
        return None


# ============================================================
# STATS (used by stats_fetcher)
# ============================================================
def fetch_stats(video_id):
    """Return {views, likes, comments} for a YouTube video."""
    try:
        yt   = _get_service()
        resp = yt.videos().list(part="statistics", id=video_id).execute()
        items = resp.get("items", [])
        if not items:
            return {}
        s = items[0]["statistics"]
        return {
            "views":    int(s.get("viewCount",    0)),
            "likes":    int(s.get("likeCount",    0)),
            "comments": int(s.get("commentCount", 0)),
        }
    except Exception as e:
        print(f"  [YouTube] Stats fetch error: {e}")
        return {}


if __name__ == "__main__":
    print("YouTube uploader — testing auth…")
    svc = _get_service()
    print("  ✅ Auth OK — token saved to token.json")

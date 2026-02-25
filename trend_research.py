"""
Dark Mind — Trend Intelligence System (v2)
4-module scraper + Groq AI analysis.

Modules:
  1. YouTube  — metadata + transcripts + viral scoring
  2. Reddit   — hot posts + pain points + demand signals
  3. Twitter  — nitter RSS trending micro-topics
  4. News     — Google News RSS breaking trends

All raw data is batched and sent to Groq for deep structured analysis.
Final output feeds directly into script_writer.py for hyper-relevant topics.
"""
import os
import sys
import json
import time
import re
import random
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

BASE_DIR     = Path(__file__).parent
YOUTUBE_KEY  = os.getenv("YOUTUBE_API_KEY")
from groq_pool import get_completion as _groq_call

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ============================================================
# NICHE CONFIG — per format
# ============================================================
YOUTUBE_QUERIES = {
    "story_lesson":      "trader lost everything finance dark story",
    "scary_truth":       "dark truth exposed scary facts history",
    "hidden_psychology": "dark psychology manipulation tactics mind",
}

REDDIT_FEEDS = {
    "story_lesson": [
        "https://www.reddit.com/r/wallstreetbets/hot.json?limit=30",
        "https://www.reddit.com/r/stocks/hot.json?limit=30",
        "https://www.reddit.com/r/investing/hot.json?limit=30",
        "https://www.reddit.com/r/entrepreneur/hot.json?limit=30",
    ],
    "scary_truth": [
        "https://www.reddit.com/r/UnresolvedMysteries/hot.json?limit=30",
        "https://www.reddit.com/r/morbidreality/hot.json?limit=30",
        "https://www.reddit.com/r/conspiracy/hot.json?limit=25",
        "https://www.reddit.com/r/todayilearned/hot.json?limit=30",
    ],
    "hidden_psychology": [
        "https://www.reddit.com/r/psychology/hot.json?limit=30",
        "https://www.reddit.com/r/socialskills/hot.json?limit=30",
        "https://www.reddit.com/r/relationship_advice/hot.json?limit=25",
        "https://www.reddit.com/r/NarcissisticAbuse/hot.json?limit=25",
    ],
}

TWITTER_SEARCHES = {
    "story_lesson":      ["trader psychology", "stock market crash story", "crypto lost everything"],
    "scary_truth":       ["dark truth nobody talks about", "government secret exposed", "scary fact"],
    "hidden_psychology": ["dark psychology", "manipulation tactics", "narcissist behavior"],
}

NEWS_KEYWORDS = {
    "story_lesson":      "stock market trader psychology wealth loss",
    "scary_truth":       "dark secret exposed cover-up investigation",
    "hidden_psychology": "psychology manipulation social media brain",
}

# Nitter instances (Twitter proxies) — tried in order
NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
]


# ============================================================
# MODULE 1 — YOUTUBE
# ============================================================
def youtube_module(format_key):
    """
    Fetches top YouTube videos for the niche.
    Returns raw data: titles, descriptions, stats, transcripts.
    """
    if not YOUTUBE_KEY:
        print("  [YouTube] No API key — skipping")
        return []

    query = YOUTUBE_QUERIES.get(format_key, "viral dark shorts")
    videos_data = []

    try:
        # Step 1: Search for top videos
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "key":           YOUTUBE_KEY,
                "q":             query,
                "part":          "snippet",
                "type":          "video",
                "order":         "viewCount",
                "maxResults":    10,
                "publishedAfter":"2024-06-01T00:00:00Z",
                "relevanceLanguage": "en",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"  [YouTube] Search error {resp.status_code}")
            return []

        items = resp.json().get("items", [])
        video_ids = [i["id"]["videoId"] for i in items if i.get("id", {}).get("videoId")]

        if not video_ids:
            return []

        # Step 2: Get video statistics and details
        stats_resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "key":  YOUTUBE_KEY,
                "id":   ",".join(video_ids),
                "part": "statistics,contentDetails,snippet",
            },
            timeout=15,
        )
        if stats_resp.status_code != 200:
            return []

        for item in stats_resp.json().get("items", []):
            snippet = item.get("snippet", {})
            stats   = item.get("statistics", {})
            details = item.get("contentDetails", {})

            views    = int(stats.get("viewCount",   0) or 0)
            likes    = int(stats.get("likeCount",   0) or 0)
            comments = int(stats.get("commentCount",0) or 0)

            # Parse duration (PT4M30S → seconds)
            duration_str = details.get("duration", "PT0S")
            duration_sec = _parse_iso_duration(duration_str)

            # Published date → days since upload
            published = snippet.get("publishedAt", "")
            days_old  = _days_since(published)

            # Engagement metrics
            like_ratio    = round(likes / views, 4)    if views > 0 else 0
            comment_ratio = round(comments / views, 4) if views > 0 else 0
            view_velocity = round(views / max(days_old, 1))   # views/day

            video_entry = {
                "video_id":     item["id"],
                "title":        snippet.get("title", ""),
                "description":  snippet.get("description", "")[:400],
                "channel":      snippet.get("channelTitle", ""),
                "views":        views,
                "likes":        likes,
                "comments":     comments,
                "duration_sec": duration_sec,
                "days_old":     days_old,
                "like_ratio":   like_ratio,
                "comment_ratio":comment_ratio,
                "view_velocity":view_velocity,
                "transcript":   "",
            }

            # Step 3: Try to fetch transcript
            transcript = _fetch_transcript(item["id"])
            if transcript:
                video_entry["transcript"] = transcript[:1500]  # cap at 1500 chars

            videos_data.append(video_entry)

        print(f"  [YouTube] {len(videos_data)} videos fetched for {format_key}")
        return videos_data

    except Exception as e:
        print(f"  [YouTube] Exception: {e}")
        return []


def _fetch_transcript(video_id):
    """Fetch YouTube transcript via youtube-transcript-api (no quota cost)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        segments = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
        return " ".join(s["text"] for s in segments)
    except ImportError:
        return ""  # package not installed
    except Exception:
        return ""


def _parse_iso_duration(iso):
    """Convert PT4M30S → total seconds."""
    try:
        h = int(re.search(r"(\d+)H", iso).group(1)) if "H" in iso else 0
        m = int(re.search(r"(\d+)M", iso).group(1)) if "M" in iso else 0
        s = int(re.search(r"(\d+)S", iso).group(1)) if "S" in iso else 0
        return h * 3600 + m * 60 + s
    except Exception:
        return 0


def _days_since(iso_date):
    """How many days since an ISO date string."""
    try:
        dt  = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return max(1, (now - dt).days)
    except Exception:
        return 30


# ============================================================
# MODULE 2 — REDDIT
# ============================================================
def reddit_module(format_key):
    """
    Fetches hot/rising posts from niche subreddits.
    Returns posts with title, body, upvotes, and top comments.
    """
    posts_data = []
    urls       = REDDIT_FEEDS.get(format_key, [])

    for url in urls[:4]:
        try:
            resp = requests.get(
                url,
                headers={**BROWSER_HEADERS, "Accept": "application/json"},
                timeout=15,
            )
            if resp.status_code != 200:
                continue

            children = resp.json().get("data", {}).get("children", [])
            for child in children[:15]:
                d = child.get("data", {})
                score    = d.get("score", 0)
                title    = d.get("title", "").strip()
                body     = d.get("selftext", "").strip()[:500]
                comments = d.get("num_comments", 0)
                url_slug = d.get("permalink", "")

                if score > 50 and title:
                    posts_data.append({
                        "subreddit": d.get("subreddit", ""),
                        "title":     title,
                        "body":      body,
                        "upvotes":   score,
                        "comments":  comments,
                        "url":       f"https://reddit.com{url_slug}",
                    })

            time.sleep(0.5)

        except Exception as e:
            print(f"  [Reddit] Error: {e}")

    # Sort by upvotes, take top 20
    posts_data.sort(key=lambda x: x["upvotes"], reverse=True)
    posts_data = posts_data[:20]

    print(f"  [Reddit] {len(posts_data)} posts for {format_key}")
    return posts_data


# ============================================================
# MODULE 3 — TWITTER/X (via Nitter RSS)
# ============================================================
def twitter_module(format_key):
    """
    Fetches trending tweets via Nitter RSS (Twitter proxy, no API key needed).
    Returns tweets with text and engagement signals.
    """
    queries  = TWITTER_SEARCHES.get(format_key, ["dark viral"])
    tweets   = []

    for query in queries[:2]:
        encoded = requests.utils.quote(query)
        for instance in NITTER_INSTANCES:
            try:
                rss_url = f"{instance}/search/rss?q={encoded}&f=tweets"
                resp    = requests.get(rss_url, headers=BROWSER_HEADERS, timeout=10)
                if resp.status_code == 200 and "<item>" in resp.text:
                    root = ET.fromstring(resp.content)
                    for item in root.findall(".//item")[:10]:
                        title = item.findtext("title", "").strip()
                        desc  = item.findtext("description", "").strip()
                        text  = re.sub(r"<[^>]+>", "", desc or title).strip()
                        if text and len(text) > 20:
                            tweets.append({
                                "text":  text[:300],
                                "query": query,
                            })
                    break  # success on this instance
            except Exception:
                continue

        time.sleep(0.3)

    print(f"  [Twitter] {len(tweets)} tweets for {format_key}")
    return tweets


# ============================================================
# MODULE 4 — NEWS (Google News RSS)
# ============================================================
def news_module(format_key):
    """
    Fetches latest news via Google News RSS.
    Returns articles with headline, summary, source, date.
    """
    keyword = NEWS_KEYWORDS.get(format_key, "viral trend")
    encoded = requests.utils.quote(keyword)
    articles = []

    try:
        url  = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"  [News] Error {resp.status_code}")
            return []

        root = ET.fromstring(resp.content)
        for item in root.findall(".//item")[:15]:
            title   = item.findtext("title", "").strip()
            desc    = item.findtext("description", "").strip()
            source  = item.findtext("source", "").strip()
            pub_date= item.findtext("pubDate", "").strip()

            # Clean HTML from description
            clean_desc = re.sub(r"<[^>]+>", "", desc).strip()

            if title and len(title) > 10:
                articles.append({
                    "headline": title,
                    "summary":  clean_desc[:400],
                    "source":   source,
                    "date":     pub_date,
                })

        print(f"  [News] {len(articles)} articles for {format_key}")
        return articles

    except Exception as e:
        print(f"  [News] Exception: {e}")
        return []


# ============================================================
# AI ANALYSIS — Groq synthesizes all 4 modules into intelligence
# ============================================================
def ai_analyze(format_key, yt_data, reddit_data, twitter_data, news_data):
    """
    Sends all raw platform data to Groq for deep analysis.
    Returns structured intelligence: topics, hooks, structure, emotions, keywords, viral scores.
    """

    # Condense data for the prompt
    yt_summary = ""
    if yt_data:
        yt_summary = "YOUTUBE VIDEOS:\n"
        for v in yt_data[:8]:
            yt_summary += (
                f"- \"{v['title']}\" | {v['views']:,} views | "
                f"{v['view_velocity']:,} views/day | like_ratio={v['like_ratio']}\n"
            )
            if v.get("transcript"):
                hook = v["transcript"][:200]
                yt_summary += f"  Hook: \"{hook}\"\n"

    reddit_summary = ""
    if reddit_data:
        reddit_summary = "REDDIT POSTS:\n"
        for p in reddit_data[:12]:
            reddit_summary += f"- [{p['upvotes']} upvotes] \"{p['title']}\"\n"
            if p.get("body"):
                reddit_summary += f"  Body: {p['body'][:150]}\n"

    twitter_summary = ""
    if twitter_data:
        twitter_summary = "TWEETS:\n"
        for t in twitter_data[:10]:
            twitter_summary += f"- \"{t['text'][:200]}\"\n"

    news_summary = ""
    if news_data:
        news_summary = "NEWS HEADLINES:\n"
        for a in news_data[:8]:
            news_summary += f"- \"{a['headline']}\" ({a['source']})\n"
            if a.get("summary"):
                news_summary += f"  {a['summary'][:200]}\n"

    if not any([yt_summary, reddit_summary, twitter_summary, news_summary]):
        return None

    prompt = f"""You are a viral content strategist analyzing platform data for a {format_key.replace('_', ' ')} channel.

Analyze the following data from YouTube, Reddit, Twitter, and News and extract deep intelligence.

{yt_summary}
{reddit_summary}
{twitter_summary}
{news_summary}

Return ONLY valid JSON:
{{
  "main_topics": ["top 5 most viral topics right now with specific angles"],
  "hook_formats": [
    {{"type": "bold_claim|question|fear|statistic|story|curiosity_gap", "example": "exact hook text that would stop someone scrolling", "effectiveness": "high|medium"}},
    {{"type": "...", "example": "...", "effectiveness": "..."}}
  ],
  "content_structures": [
    {{"pattern": "problem_solution|story_lesson|list|tutorial", "description": "how this structure works for this niche"}}
  ],
  "emotional_triggers": ["fear", "urgency", "authority", "inspiration", "controversy"],
  "top_keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
  "viral_angles": [
    {{"topic": "specific angle", "why_it_works": "psychological reason", "viral_score": 85}}
  ],
  "audience_pain_points": ["top 3 problems the audience is experiencing right now"],
  "best_topic_right_now": "single most viral-worthy topic to make a video about today"
}}"""

    try:
        content = _groq_call(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1500,
        )

        # Extract JSON
        if "```" in content:
            for part in content.split("```"):
                part = part.strip().lstrip("json").strip()
                if part.startswith("{"):
                    content = part
                    break
        if not content.startswith("{"):
            start = content.find("{")
            if start != -1:
                content = content[start:]
        last = content.rfind("}")
        if last != -1:
            content = content[:last + 1]

        return json.loads(content)

    except Exception as e:
        print(f"  [AI Analysis] Error: {e}")
        return None


# ============================================================
# FULL RESEARCH RUN — all 4 modules + AI synthesis
# ============================================================
def get_trending_topics():
    """
    Runs all 4 modules for each format, runs AI analysis,
    and returns dict of topics + intelligence per format.
    Also writes topics_queue.json.
    """
    print("\n🔍 Running Trend Intelligence System...")

    result     = {}
    full_intel = {}

    for fmt in ["story_lesson", "scary_truth", "hidden_psychology"]:
        print(f"\n  📊 [{fmt}]")

        yt_data      = youtube_module(fmt)
        reddit_data  = reddit_module(fmt)
        twitter_data = twitter_module(fmt)
        news_data    = news_module(fmt)

        # AI synthesis
        intel = ai_analyze(fmt, yt_data, reddit_data, twitter_data, news_data)

        if intel:
            # Extract topic list for backwards compatibility
            topics = []
            if intel.get("best_topic_right_now"):
                topics.append(intel["best_topic_right_now"])
            topics += intel.get("main_topics", [])[:4]
            result[fmt] = topics[:5]
            full_intel[fmt] = intel
            print(f"  ✅ Best topic: {intel.get('best_topic_right_now', 'N/A')[:70]}")
        else:
            # Fallback: just collect raw titles
            raw = []
            for p in reddit_data[:5]:
                raw.append(p["title"])
            for a in news_data[:3]:
                raw.append(a["headline"])
            result[fmt] = raw[:5]

    # Persist
    queue_path = BASE_DIR / "topics_queue.json"
    queue_path.write_text(
        json.dumps({
            "timestamp":  time.time(),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "topics":     result,
            "intelligence": full_intel,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    total = sum(len(v) for v in result.values())
    print(f"\n✅ Intelligence saved — {total} topics across formats")
    return result


# ============================================================
# CACHED — use fresh data if < 2 hours old
# ============================================================
def get_topics_cached():
    queue_path = BASE_DIR / "topics_queue.json"
    try:
        data = json.loads(queue_path.read_text(encoding="utf-8"))
        age  = time.time() - data.get("timestamp", 0)
        if age < 7200:
            cached = data.get("topics", {})
            if cached:
                print(f"   Using cached trends ({int(age//60)}min old)")
                return cached
    except Exception:
        pass
    return get_trending_topics()


def get_intelligence_for_format(format_key):
    """
    Returns the full AI intelligence object for a specific format.
    Used by script_writer to get hooks, keywords, emotional triggers.
    """
    queue_path = BASE_DIR / "topics_queue.json"
    try:
        data = json.loads(queue_path.read_text(encoding="utf-8"))
        age  = time.time() - data.get("timestamp", 0)
        if age < 7200:
            return data.get("intelligence", {}).get(format_key, {})
    except Exception:
        pass
    return {}


# ============================================================
# TEST
# ============================================================
if __name__ == "__main__":
    topics = get_trending_topics()
    print("\n" + "=" * 60)
    for fmt, t_list in topics.items():
        print(f"\n{fmt.upper()}:")
        for i, t in enumerate(t_list, 1):
            print(f"  {i}. {t}")

    # Show full intelligence for story_lesson
    queue_path = BASE_DIR / "topics_queue.json"
    try:
        data  = json.loads(queue_path.read_text())
        intel = data.get("intelligence", {}).get("story_lesson", {})
        if intel:
            print(f"\n🧠 STORY LESSON INTELLIGENCE:")
            print(f"  Best topic: {intel.get('best_topic_right_now')}")
            print(f"  Top keywords: {intel.get('top_keywords')}")
            print(f"  Hook formats: {[h['type'] for h in intel.get('hook_formats', [])]}")
            print(f"  Emotional triggers: {intel.get('emotional_triggers')}")
            print(f"  Pain points: {intel.get('audience_pain_points')}")
    except Exception:
        pass

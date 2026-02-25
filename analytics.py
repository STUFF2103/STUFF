"""
Dark Mind — Analytics & Learning Engine
Tracks every video created, learns which formats/topics/hours pump.
Auto-refreshed after every run. Drives scheduler's smart decisions.
"""
import os
import sys
import json
import time
import random
import sqlite3
from pathlib import Path
from datetime import datetime

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent
DB_PATH  = BASE_DIR / "analytics.db"

# ============================================================
# PSYCHOLOGY OF VIRALITY — default peaks when no data yet
# Backed by TikTok/Shorts algorithm research:
#   7-9am   → morning commute (captive, full attention)
#   12-1pm  → lunch break (boredom peak, high share intent)
#   7-10pm  → prime time (highest volume)
#   Saturday 11am-1pm → bored weekend scroll
# These are used until the DB has enough real data.
# ============================================================
PSYCHOLOGY_PEAK_HOURS = {
    0: [7, 8, 12, 19, 20],        # Monday
    1: [7, 8, 12, 19, 20, 21],    # Tuesday  ← statistically best day
    2: [7, 8, 12, 19, 20, 21],    # Wednesday
    3: [7, 8, 12, 19, 20],        # Thursday
    4: [7, 8, 12, 19],            # Friday (afternoon drops off)
    5: [10, 11, 12, 14, 20],      # Saturday
    6: [11, 12, 14, 19],          # Sunday
}

# Minimum views to consider a video "pumped"
PUMP_THRESHOLD = 10_000


# ============================================================
# SCHEMA + INIT
# ============================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id            TEXT UNIQUE,
            format            TEXT,
            topic             TEXT,
            hook_text         TEXT,
            voice_type        TEXT,
            suggested_music   TEXT,
            post_hour         INTEGER,
            post_day_of_week  INTEGER,
            created_at        REAL,
            output_path       TEXT,
            views             INTEGER DEFAULT 0,
            likes             INTEGER DEFAULT 0,
            comments          INTEGER DEFAULT 0,
            shares            INTEGER DEFAULT 0,
            watch_time_avg    REAL    DEFAULT 0,
            engagement_rate   REAL    DEFAULT 0,
            pumped            INTEGER DEFAULT 0,
            youtube_id        TEXT    DEFAULT '',
            tiktok_id         TEXT    DEFAULT '',
            youtube_url       TEXT    DEFAULT '',
            tiktok_url        TEXT    DEFAULT '',
            last_stats_fetch  REAL    DEFAULT 0
        )
    """)

    # Migration: add platform columns to existing DBs
    for col, typedef in [
        ("youtube_id",       "TEXT DEFAULT ''"),
        ("tiktok_id",        "TEXT DEFAULT ''"),
        ("youtube_url",      "TEXT DEFAULT ''"),
        ("tiktok_url",       "TEXT DEFAULT ''"),
        ("last_stats_fetch", "REAL DEFAULT 0"),
    ]:
        try:
            c.execute(f"ALTER TABLE videos ADD COLUMN {col} {typedef}")
        except Exception:
            pass  # already exists

    c.execute("""
        CREATE TABLE IF NOT EXISTS hourly_performance (
            hour              INTEGER PRIMARY KEY,
            avg_views         REAL    DEFAULT 0,
            avg_engagement    REAL    DEFAULT 0,
            total_videos      INTEGER DEFAULT 0,
            last_updated      REAL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS format_performance (
            format            TEXT    PRIMARY KEY,
            avg_views         REAL    DEFAULT 0,
            avg_engagement    REAL    DEFAULT 0,
            total_videos      INTEGER DEFAULT 0,
            best_topics       TEXT    DEFAULT '[]',
            last_updated      REAL
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# LOG NEW VIDEO
# ============================================================
def log_video(run_id, script_data, output_path):
    """Call this right after a video is created successfully."""
    now = datetime.now()
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT OR IGNORE INTO videos
                (run_id, format, topic, hook_text, voice_type, suggested_music,
                 post_hour, post_day_of_week, created_at, output_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(run_id),
            script_data.get("format", ""),
            script_data.get("topic", ""),
            script_data.get("hook_text", ""),
            script_data.get("voice_type", ""),
            script_data.get("suggested_music", ""),
            now.hour,
            now.weekday(),
            time.time(),
            str(output_path),
        ))
        conn.commit()
        conn.close()
        print(f"📊 Analytics: logged run {run_id}")
    except Exception as e:
        print(f"  [Analytics] log_video error: {e}")


# ============================================================
# UPDATE PERFORMANCE (call after you check social stats)
# ============================================================
def update_performance(run_id, views=0, likes=0, comments=0,
                       shares=0, watch_time_avg=0):
    """
    Update view/engagement metrics for a video.
    Call this manually or from a social-stats-checker script.
    """
    engagement = (likes + comments + shares) / max(views, 1) * 100
    pumped     = 1 if views >= PUMP_THRESHOLD else 0

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            UPDATE videos
            SET views=?, likes=?, comments=?, shares=?,
                watch_time_avg=?, engagement_rate=?, pumped=?
            WHERE run_id=?
        """, (views, likes, comments, shares,
              watch_time_avg, engagement, pumped, str(run_id)))
        conn.commit()
        conn.close()
        _recalculate_aggregates()
        print(f"📊 Analytics: updated run {run_id} → {views:,} views, pumped={bool(pumped)}")
    except Exception as e:
        print(f"  [Analytics] update_performance error: {e}")


# ============================================================
# RECALCULATE AGGREGATES
# ============================================================
def _recalculate_aggregates():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        now = time.time()

        # Hourly aggregates
        for hour in range(24):
            c.execute("""
                SELECT AVG(views), AVG(engagement_rate), COUNT(*)
                FROM videos WHERE post_hour=? AND views > 0
            """, (hour,))
            row = c.fetchone()
            if row and row[2] > 0:
                c.execute("""
                    INSERT OR REPLACE INTO hourly_performance
                        (hour, avg_views, avg_engagement, total_videos, last_updated)
                    VALUES (?, ?, ?, ?, ?)
                """, (hour, row[0] or 0, row[1] or 0, row[2], now))

        # Format aggregates
        for fmt in ["story_lesson", "scary_truth", "hidden_psychology"]:
            c.execute("""
                SELECT AVG(views), AVG(engagement_rate), COUNT(*)
                FROM videos WHERE format=? AND views > 0
            """, (fmt,))
            row = c.fetchone()

            # Top pumped topics for this format
            c.execute("""
                SELECT topic FROM videos
                WHERE format=? AND pumped=1
                ORDER BY views DESC LIMIT 10
            """, (fmt,))
            topics = [r[0] for r in c.fetchall()]

            if row and row[2] > 0:
                c.execute("""
                    INSERT OR REPLACE INTO format_performance
                        (format, avg_views, avg_engagement, total_videos,
                         best_topics, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (fmt, row[0] or 0, row[1] or 0, row[2],
                      json.dumps(topics), now))

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  [Analytics] recalculate error: {e}")


# ============================================================
# QUERY HELPERS — used by scheduler
# ============================================================
def get_best_post_hour():
    """
    Returns the hour with highest avg engagement.
    Falls back to psychology-backed peaks if DB has < 3 data points.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT hour, avg_engagement, total_videos
            FROM hourly_performance
            WHERE total_videos >= 3
            ORDER BY avg_engagement DESC LIMIT 1
        """)
        row = c.fetchone()
        conn.close()
        if row:
            return row[0]
    except Exception:
        pass

    # Psychology default: best hour for today's day-of-week
    today  = datetime.now().weekday()
    peaks  = PSYCHOLOGY_PEAK_HOURS.get(today, [7, 8, 12, 19, 20])
    return random.choice(peaks)


def get_best_format():
    """Returns format with highest avg views (min 3 videos tracked)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT format, avg_views FROM format_performance
            WHERE total_videos >= 3
            ORDER BY avg_views DESC LIMIT 1
        """)
        row = c.fetchone()
        conn.close()
        if row:
            return row[0]
    except Exception:
        pass
    return None


def get_pumped_topics(format_key):
    """Return topics that have crossed the pump threshold for this format."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT topic, views FROM videos
            WHERE format=? AND pumped=1
            ORDER BY views DESC LIMIT 8
        """, (format_key,))
        rows = c.fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def get_all_used_topics():
    """
    Returns {"used": [...all topics ever made...], "pumped": [...topics that went viral...]}.
    Used by run_pipeline to skip already-used topics (unless they pumped).
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT topic, pumped FROM videos WHERE topic != '' ORDER BY created_at DESC")
        rows = c.fetchall()
        conn.close()
        used   = [r[0] for r in rows if r[0]]
        pumped = [r[0] for r in rows if r[1] == 1 and r[0]]
        return {"used": used, "pumped": pumped}
    except Exception:
        return {"used": [], "pumped": []}


def get_used_hooks(limit=20):
    """
    Returns the last `limit` hook_text values so the script writer
    can avoid generating the same hook again.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT hook_text FROM videos WHERE hook_text != '' ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
        rows = c.fetchall()
        conn.close()
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []


def get_viral_candidates():
    """
    Returns videos that went viral (pumped=1) but don't have a follow-up yet.
    A follow-up is detected by checking if any later video used the same topic.
    Returns list of dicts: {run_id, topic, format, views, hook_text}
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT run_id, topic, format, views, hook_text, created_at
            FROM videos
            WHERE pumped=1 AND topic != ''
            ORDER BY views DESC
        """)
        pumped = c.fetchall()

        results = []
        for row in pumped:
            run_id, topic, fmt, views, hook_text, created_at = row
            # Check if a follow-up was already made (any video with same topic made after this one)
            c.execute("""
                SELECT COUNT(*) FROM videos
                WHERE topic=? AND created_at > ? AND run_id != ?
            """, (topic, created_at, run_id))
            followup_count = c.fetchone()[0]
            if followup_count == 0:
                results.append({
                    "run_id":    run_id,
                    "topic":     topic,
                    "format":    fmt,
                    "views":     views,
                    "hook_text": hook_text,
                })
        conn.close()
        return results
    except Exception:
        return []


def get_today_video_count():
    """How many videos have been created today."""
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM videos WHERE created_at >= ?", (today_start,))
        count = c.fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0


def get_psychology_peaks_today():
    """Return psychology-backed peak hours for today."""
    today = datetime.now().weekday()
    return PSYCHOLOGY_PEAK_HOURS.get(today, [7, 8, 12, 19, 20])


def get_best_hours_for_day(day_of_week, n=4):
    """
    Returns top N best posting hours for a specific weekday, learned from past data.
    Tiered fallback:
      1. Day-specific engagement data (min 2 videos per hour slot)
      2. Any-day overall hourly data (min 3 videos) — catches early-stage data
      3. Empty list → caller uses psychology peaks
    Hours are returned sorted by avg_engagement descending.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Tier 1: day-specific learned hours
        c.execute("""
            SELECT post_hour, AVG(engagement_rate) as avg_eng, COUNT(*) as cnt
            FROM videos
            WHERE post_day_of_week = ? AND views > 0
            GROUP BY post_hour
            HAVING cnt >= 2
            ORDER BY avg_eng DESC
            LIMIT ?
        """, (day_of_week, n))
        rows = c.fetchall()

        if rows:
            conn.close()
            return [r[0] for r in rows]

        # Tier 2: any-day overall hourly data
        c.execute("""
            SELECT hour, avg_engagement, total_videos
            FROM hourly_performance
            WHERE total_videos >= 3
            ORDER BY avg_engagement DESC
            LIMIT ?
        """, (n,))
        rows2 = c.fetchall()
        conn.close()
        return [r[0] for r in rows2] if rows2 else []

    except Exception:
        return []


def save_platform_ids(run_id, youtube_id=None, tiktok_id=None):
    """Store YouTube / TikTok video IDs after uploading."""
    yt_id  = youtube_id or ""
    tt_id  = tiktok_id  or ""
    yt_url = f"https://youtube.com/shorts/{yt_id}" if yt_id else ""
    tt_url = f"https://www.tiktok.com/@/video/{tt_id}" if tt_id else ""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            UPDATE videos
            SET youtube_id=?, tiktok_id=?, youtube_url=?, tiktok_url=?
            WHERE run_id=?
        """, (yt_id, tt_id, yt_url, tt_url, str(run_id)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  [Analytics] save_platform_ids error: {e}")


def get_videos_for_stats_fetch(max_age_days=30):
    """
    Return videos that have at least one platform ID and were posted
    within the last max_age_days. Used by the stats fetcher.
    Returns list of dicts.
    """
    cutoff = time.time() - max_age_days * 86400
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT run_id, youtube_id, tiktok_id, views, likes, comments, shares
            FROM videos
            WHERE created_at >= ?
              AND (youtube_id != '' OR tiktok_id != '')
            ORDER BY created_at DESC
        """, (cutoff,))
        rows = c.fetchall()
        conn.close()
        return [
            {
                "run_id":     r[0],
                "youtube_id": r[1],
                "tiktok_id":  r[2],
                "views":      r[3],
                "likes":      r[4],
                "comments":   r[5],
                "shares":     r[6],
            }
            for r in rows
        ]
    except Exception:
        return []


def get_hour_confidence(day_of_week):
    """
    Returns a dict with learning status for today:
      {"day_videos": int, "any_videos": int, "data_driven": bool, "tier": str}
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM videos WHERE post_day_of_week = ? AND views > 0",
            (day_of_week,)
        )
        day_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM videos WHERE views > 0")
        any_count = c.fetchone()[0]
        conn.close()

        if day_count >= 4:
            tier = "day-specific"
        elif any_count >= 6:
            tier = "cross-day"
        else:
            tier = "psychology"

        return {
            "day_videos": day_count,
            "any_videos": any_count,
            "data_driven": tier != "psychology",
            "tier": tier,
        }
    except Exception:
        return {"day_videos": 0, "any_videos": 0, "data_driven": False, "tier": "psychology"}


# ============================================================
# SUMMARY REPORT
# ============================================================
def print_analytics_summary():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("SELECT COUNT(*), AVG(views), MAX(views) FROM videos")
        total = c.fetchone()

        c.execute("SELECT COUNT(*) FROM videos WHERE pumped=1")
        pumped_count = c.fetchone()[0]

        c.execute("""
            SELECT hour, avg_views, total_videos
            FROM hourly_performance ORDER BY avg_views DESC LIMIT 3
        """)
        top_hours = c.fetchall()

        c.execute("""
            SELECT format, avg_views, total_videos
            FROM format_performance ORDER BY avg_views DESC
        """)
        fmt_rows = c.fetchall()

        conn.close()

        print("\n" + "="*55)
        print("  📊 DARK MIND ANALYTICS SUMMARY")
        print("="*55)
        print(f"   Total videos created : {total[0]}")
        print(f"   Pumped (>{PUMP_THRESHOLD:,} views)  : {pumped_count}")
        if total[1]:
            print(f"   Avg views            : {total[1]:,.0f}")
            print(f"   Best video           : {total[2]:,.0f} views")

        if top_hours:
            hours_str = ", ".join(f"{h[0]:02d}:00" for h in top_hours)
            print(f"   Best post hours      : {hours_str}")

        if fmt_rows:
            print("\n   Format performance:")
            for row in fmt_rows:
                print(f"     {row[0]:22s} avg {row[1]:,.0f} views  ({row[2]} videos)")

        print("="*55)
    except Exception as e:
        print(f"  [Analytics] summary error: {e}")


# ============================================================
# AUTO-INIT
# ============================================================
init_db()


if __name__ == "__main__":
    print_analytics_summary()
    print(f"\n  Best post hour today : {get_best_post_hour():02d}:00")
    print(f"  Best format          : {get_best_format() or 'no data yet'}")
    print(f"  Videos today         : {get_today_video_count()}")
    print(f"  Psychology peaks     : {get_psychology_peaks_today()}")

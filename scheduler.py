"""
Dark Mind — Hourly Auto-Scheduler
Runs the full pipeline every active hour (6am-11pm).
Psychology-aware: posts at peak engagement times per day-of-week.
Learns from analytics DB: best format, best topic angle, best hour.

Usage:
    python scheduler.py              # Start continuous scheduler
    python scheduler.py --run-now   # Force one run immediately (ignores hour check)
    python scheduler.py --stats     # Print analytics summary + exit
"""
import os
import sys
import time
import json
import random
import argparse
import threading
from pathlib import Path
from datetime import datetime

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent

# ============================================================
# SCHEDULE CONFIG
# ============================================================
ACTIVE_HOURS_START = 6    # 6 AM — don't run before this
ACTIVE_HOURS_END   = 23   # 11 PM — don't run at or after this
CHECK_INTERVAL_MIN = 5    # How often to check if it's time to run (minutes)

_DEFAULT_MAX_VIDEOS = 4   # Fallback if settings.json not found


def get_max_videos_per_day() -> int:
    try:
        settings_path = BASE_DIR / "settings.json"
        if settings_path.exists():
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            return int(data.get("max_videos_per_day", _DEFAULT_MAX_VIDEOS))
    except Exception:
        pass
    return _DEFAULT_MAX_VIDEOS

# Psychology-backed peak hours per weekday (0=Monday, 6=Sunday)
# These inform the scheduler to PREFER running during these windows.
# Based on TikTok/YouTube Shorts algorithm research:
#   - Tuesday & Wednesday have highest organic reach
#   - 7-9am catches morning commute (captive + full attention)
#   - 12-1pm = lunch scroll (boredom peak + high share intent)
#   - 7-10pm = prime time (highest volume, but also most competition)
PEAK_HOURS = {
    0: [7, 8, 12, 19, 20],        # Monday
    1: [7, 8, 12, 19, 20, 21],    # Tuesday ← best day statistically
    2: [7, 8, 12, 19, 20, 21],    # Wednesday ← second best
    3: [7, 8, 12, 19, 20],        # Thursday
    4: [7, 8, 12, 19],            # Friday (afternoon engagement drops)
    5: [10, 11, 12, 14, 20],      # Saturday (late morning + evening)
    6: [11, 12, 14, 19],          # Sunday (slower, leisure browsing)
}

# State (in-memory for current process)
_last_run_hour   = -1
_daily_run_count = {"date": "", "count": 0}

# Daily adaptive schedule cache (rebuilt each new day)
_today_schedule  = []
_schedule_date   = ""

# Stats fetch tracking
_last_stats_fetch = 0.0          # Unix timestamp of last stats fetch
STATS_FETCH_INTERVAL = 2 * 3600  # 2 hours between automatic fetches


# ============================================================
# HELPERS
# ============================================================
def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def is_active_hour():
    h = datetime.now().hour
    return ACTIVE_HOURS_START <= h < ACTIVE_HOURS_END


def get_daily_count():
    today = datetime.now().strftime("%Y-%m-%d")
    if _daily_run_count["date"] != today:
        _daily_run_count["date"]  = today
        _daily_run_count["count"] = 0

        # Also query DB for real count (handles restarts)
        try:
            from analytics import get_today_video_count
            _daily_run_count["count"] = get_today_video_count()
        except Exception:
            pass

    return _daily_run_count["count"]


def inc_daily_count():
    get_daily_count()   # Ensure date is current
    _daily_run_count["count"] += 1


# ============================================================
# ADAPTIVE DAILY SCHEDULE
# ============================================================
def build_daily_schedule():
    """
    Builds today's posting schedule by blending:
      1. Learned hours from analytics DB (engagement-ranked, day-of-week specific)
      2. Psychology-backed peak hours as fallback / filler slots

    Each slot gets a random minute offset (5-55 min) so posts never land on
    the exact hour — looks natural, varies every day.
    Returns a sorted list of (hour, minute) tuples.
    """
    now      = datetime.now()
    weekday  = now.weekday()
    max_vids = get_max_videos_per_day()

    # Step 1: ask analytics for learned hours for today's weekday
    learned = []
    tier    = "psychology"
    try:
        from analytics import get_best_hours_for_day, get_hour_confidence
        learned = get_best_hours_for_day(weekday, n=max_vids)
        conf    = get_hour_confidence(weekday)
        tier    = conf.get("tier", "psychology")
    except Exception:
        pass

    # Step 2: psychology defaults for today
    psych = PEAK_HOURS.get(weekday, [7, 8, 12, 19, 20])

    # Step 3: merge — learned first, fill remaining slots with psychology peaks
    seen     = set()
    combined = []
    for h in (learned + psych):
        if h not in seen:
            seen.add(h)
            combined.append(h)

    # Step 4: keep only active-window hours, take up to max_vids (earliest first)
    active = sorted(h for h in combined if ACTIVE_HOURS_START <= h < ACTIVE_HOURS_END)
    chosen_hours = active[:max_vids]

    # Step 5: add random jitter — each slot fires at a random minute (5-55)
    # so it never looks like a bot posting at exactly :00 every day
    chosen = [(h, random.randint(5, 55)) for h in chosen_hours]

    day_name = now.strftime("%A")
    slots    = [f"{h:02d}:{m:02d}" for h, m in chosen]
    learned_slots = [f"{h:02d}:xx" for h in learned]

    print(f"\n  📅 {day_name}'s posting schedule : {slots}")
    if tier == "day-specific":
        print(f"  🧠 Fully learned ({day_name}-specific data) — psychology ignored")
    elif tier == "cross-day":
        print(f"  📈 Partially learned (cross-day data) — {learned_slots} + psych fill")
    else:
        print(f"  🔮 Psychology defaults (not enough data yet for {day_name})")

    return chosen


def get_today_schedule():
    """Return (and cache) today's posting schedule. Rebuilds at midnight."""
    global _today_schedule, _schedule_date
    today = datetime.now().strftime("%Y-%m-%d")
    if _schedule_date != today or not _today_schedule:
        _today_schedule = build_daily_schedule()
        _schedule_date  = today
    return _today_schedule


def should_run_now():
    global _last_run_hour
    now = datetime.now()

    if not is_active_hour():
        return False, f"Outside active hours ({ACTIVE_HOURS_START}:00-{ACTIVE_HOURS_END}:00)"

    if now.hour == _last_run_hour:
        return False, "Already ran this hour"

    count    = get_daily_count()
    max_vids = get_max_videos_per_day()
    if count >= max_vids:
        return False, f"Daily cap reached ({count}/{max_vids})"

    # Check against today's jittered schedule (list of (hour, minute) tuples)
    schedule = get_today_schedule()
    schedule_hours = [h for h, m in schedule]

    if now.hour not in schedule_hours:
        future = [(h, m) for h, m in schedule if h > now.hour]
        nxt    = f"{future[0][0]:02d}:{future[0][1]:02d}" if future else "none remaining today"
        return False, f"Not a scheduled slot — next: {nxt}"

    # We're in a scheduled hour — check if we've hit or passed the target minute
    target_minute = next(m for h, m in schedule if h == now.hour)
    if now.minute < target_minute:
        return False, f"Waiting for :{target_minute:02d} (now :{now.minute:02d})"

    return True, "OK"


# ============================================================
# INTELLIGENCE — picks best format + topic using analytics
# ============================================================
def get_intelligence():
    """
    Returns (format_key, topic_hint) using:
      1. Analytics DB: which format/topic previously pumped
      2. Trend research: what's hot right now
      3. Psychology defaults as final fallback
    """
    try:
        from analytics import get_best_format, get_pumped_topics
        format_key = get_best_format()
    except Exception:
        format_key = None

    if not format_key:
        # Rotate formats equally if no analytics data
        format_key = random.choice(["story_lesson", "scary_truth", "hidden_psychology"])

    # Get topics that previously pumped
    pumped_topics = []
    try:
        from analytics import get_pumped_topics
        pumped_topics = get_pumped_topics(format_key)
    except Exception:
        pass

    # Get trending topics
    trending = []
    try:
        from trend_research import get_topics_cached
        trend_data = get_topics_cached()
        trending = trend_data.get(format_key, [])
    except Exception as e:
        print(f"  [Scheduler] Trend fetch skipped: {e}")

    # Decision logic:
    # - 30% chance: remix a previously pumped topic (proven winner)
    # - 50% chance: use a trending topic (fresh relevance)
    # - 20% chance: free-form (default format topics — avoids filter bubble)
    topic_hint = None
    roll = random.random()

    if pumped_topics and roll < 0.30:
        base = random.choice(pumped_topics)
        topic_hint = f"new angle on: {base}"
        print(f"  [Scheduler] Remixing pumped winner: {base}")
    elif trending and roll < 0.80:
        topic_hint = random.choice(trending)
        print(f"  [Scheduler] Using trend: {topic_hint}")
    else:
        print(f"  [Scheduler] Free-form run for {format_key}")

    return format_key, topic_hint


# ============================================================
# RUN ONE PIPELINE CYCLE
# ============================================================
def run_once(force=False):
    global _last_run_hour, _last_stats_fetch

    if not force:
        ok, reason = should_run_now()
        if not ok:
            print(f"[{now_str()}] ⏭  Skip: {reason}")
            return False

    now = datetime.now()
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  🤖 AUTO-RUN — {now.strftime('%A %Y-%m-%d %H:%M')}")
    schedule = get_today_schedule()
    schedule_str = ", ".join(f"{h:02d}:{m:02d}" for h, m in schedule) or "none"
    in_slot = datetime.now().hour in [h for h, m in schedule]
    print(f"  Scheduled   : {schedule_str}  {'← NOW 🔥' if in_slot else ''}")
    print(f"  Daily count : {get_daily_count()}/{get_max_videos_per_day()}")
    print(f"{sep}")

    format_key, topic_hint = get_intelligence()

    try:
        from run_pipeline import run_pipeline

        # Check if any viral video needs a follow-up first
        viral_topic = None
        try:
            from analytics import get_viral_candidates
            candidates = get_viral_candidates()
            if candidates:
                best = candidates[0]
                viral_topic = best["topic"]
                print(f"\n🔥 VIRAL FOLLOW-UP triggered: '{viral_topic[:60]}' ({best['views']:,} views)")
        except Exception:
            pass

        if viral_topic:
            result = run_pipeline(
                manual_idea=viral_topic,
                viral_followup=True,
            )
        else:
            result = run_pipeline(
                manual_idea=topic_hint,
                trend_data=None,
            )

        if result:
            _last_run_hour = now.hour
            inc_daily_count()
            # run_pipeline already fetched stats right after upload;
            # update our timer so the periodic check doesn't re-fetch immediately
            _last_stats_fetch = time.time()
            print(f"\n✅ [{now_str()}] Auto-run complete: {result}")
            return True
        else:
            print(f"\n❌ [{now_str()}] Auto-run pipeline failed")
            return False

    except Exception as e:
        print(f"\n❌ [{now_str()}] Auto-run exception: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# PERIODIC STATS FETCH
# ============================================================
def maybe_fetch_stats():
    """
    Fetch stats for all recent videos if > STATS_FETCH_INTERVAL seconds
    have passed since the last fetch. Called in the main scheduler loop.
    """
    global _last_stats_fetch
    if time.time() - _last_stats_fetch < STATS_FETCH_INTERVAL:
        return
    try:
        from stats_fetcher import fetch_and_update_all
        print(f"\n📊 [{now_str()}] Periodic stats fetch (>2h since last)…")
        fetch_and_update_all()
        _last_stats_fetch = time.time()
    except Exception as e:
        print(f"  [Scheduler] Stats fetch error: {e}")


# ============================================================
# MAIN SCHEDULER LOOP
# ============================================================
def start_scheduler():
    try:
        import schedule
    except ImportError:
        print("Installing schedule...")
        os.system(f"{sys.executable} -m pip install schedule -q")
        import schedule

    now = datetime.now()
    print("\n" + "="*60)
    print("  🤖 DARK MIND AUTO-SCHEDULER")
    print("="*60)
    print(f"  Active hours  : {ACTIVE_HOURS_START}:00 → {ACTIVE_HOURS_END}:00")
    print(f"  Max/day       : {get_max_videos_per_day()} videos")
    print(f"  Check every   : {CHECK_INTERVAL_MIN} minutes")
    print(f"  Current time  : {now.strftime('%H:%M')}")
    print("  Press Ctrl+C to stop.")
    print("="*60 + "\n")

    # Show analytics before starting
    try:
        from analytics import print_analytics_summary
        print_analytics_summary()
    except Exception:
        pass

    # Build and show today's adaptive schedule
    todays_schedule = get_today_schedule()

    # Schedule the check every N minutes
    schedule.every(CHECK_INTERVAL_MIN).minutes.do(run_once)

    # If current hour is already a scheduled slot → run immediately
    if is_active_hour() and now.hour in [h for h, m in todays_schedule]:
        ok, reason = should_run_now()
        if ok:
            print(f"🔥 Current hour ({now.strftime('%H:%M')}) is a scheduled slot — starting now!")
            threading.Thread(target=run_once, daemon=True).start()

    while True:
        try:
            schedule.run_pending()
            maybe_fetch_stats()   # Checks interval internally — noop if < 2h
            time.sleep(30)
        except KeyboardInterrupt:
            print("\n👋 Scheduler stopped.")
            break
        except Exception as e:
            print(f"[{now_str()}] Scheduler loop error: {e}")
            time.sleep(60)


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dark Mind Auto-Scheduler")
    parser.add_argument("--run-now", action="store_true", help="Force one run immediately")
    parser.add_argument("--stats",   action="store_true", help="Print analytics and exit")
    args = parser.parse_args()

    if args.stats:
        from analytics import print_analytics_summary, get_best_post_hour, get_best_format
        print_analytics_summary()
        print(f"\n  Best hour today : {get_best_post_hour():02d}:00")
        print(f"  Best format     : {get_best_format() or 'no data yet'}")
        sys.exit(0)

    if args.run_now:
        run_once(force=True)
    else:
        start_scheduler()

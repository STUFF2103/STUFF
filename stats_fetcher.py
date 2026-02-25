"""
Dark Mind — Stats Fetcher
Pulls view/like/comment/share counts from YouTube and TikTok
and feeds them into the analytics DB via update_performance().

Called:
  1. Immediately after every successful upload (run_pipeline.py)
  2. Every 2 hours by the scheduler (for videos posted in the last 30 days)
"""
import sys
from datetime import datetime

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def fetch_and_update_all():
    """
    Fetch stats for all recently uploaded videos (last 30 days).
    Merges YouTube + TikTok data and calls update_performance().
    """
    from analytics import get_videos_for_stats_fetch, update_performance

    videos = get_videos_for_stats_fetch(max_age_days=30)
    if not videos:
        print("  [Stats] No videos to update.")
        return

    print(f"\n📊 [{datetime.now().strftime('%H:%M')}] Fetching stats for {len(videos)} video(s)…")

    updated = 0
    for v in videos:
        run_id     = v["run_id"]
        youtube_id = v.get("youtube_id", "")
        tiktok_id  = v.get("tiktok_id",  "")

        yt_stats = {}
        tt_stats = {}

        # ── YouTube ──────────────────────────────────────────
        if youtube_id:
            try:
                from uploader_youtube import fetch_stats as yt_fetch
                yt_stats = yt_fetch(youtube_id)
            except Exception as e:
                print(f"  [Stats] YouTube fetch error ({run_id}): {e}")

        # ── TikTok ───────────────────────────────────────────
        if tiktok_id:
            try:
                from uploader_tiktok import fetch_stats as tt_fetch
                tt_stats = tt_fetch(tiktok_id)
            except Exception as e:
                print(f"  [Stats] TikTok fetch error ({run_id}): {e}")

        if not yt_stats and not tt_stats:
            continue

        # Merge: take MAX across platforms for each metric
        # (conservative — counts each platform separately would double-count)
        merged = {
            "views":    max(yt_stats.get("views",    0), tt_stats.get("views",    0)),
            "likes":    max(yt_stats.get("likes",    0), tt_stats.get("likes",    0)),
            "comments": max(yt_stats.get("comments", 0), tt_stats.get("comments", 0)),
            "shares":   tt_stats.get("shares", 0),   # only TikTok reports shares
        }

        # Only update if numbers went up (never overwrite with stale data)
        if merged["views"] > v.get("views", 0) or updated == 0:
            update_performance(
                run_id,
                views=merged["views"],
                likes=merged["likes"],
                comments=merged["comments"],
                shares=merged["shares"],
            )
            updated += 1

    print(f"  [Stats] Done — {updated}/{len(videos)} records updated.")
    return updated

"""
Dark Mind — Full Pipeline Runner
Usage:
    python run_pipeline.py                          # auto topic + trend research
    python run_pipeline.py --idea "your topic"      # manual topic
    python run_pipeline.py --trend "trending thing" # trend-aware topic
"""
import os
import re
import sys
import json
import time
import random
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent

# ── PUBLISH TOGGLE ────────────────────────────────────────────
# Set to False to produce the video locally without uploading
PUBLISH = False
# ─────────────────────────────────────────────────────────────

# Stop-words ignored when comparing topic similarity
_STOP = {
    "the","a","an","of","in","to","how","why","what","is","are","was","were",
    "be","been","i","you","we","they","it","this","that","for","on","at","by",
    "with","from","and","or","but","do","does","did","have","has","had","not",
    "no","so","if","as","can","will","just","about","into","its","s","your",
}


def _topic_words(topic):
    """Return meaningful lowercased words from a topic string."""
    return set(re.sub(r"[^a-z0-9 ]", "", topic.lower()).split()) - _STOP


def _topic_is_fresh(candidate, used_info):
    """
    True  → topic is new (safe to use).
    False → topic was already used AND did NOT go viral (skip it).
    A topic that DID go viral (pumped=1) is always allowed to repeat.
    """
    cand_words = _topic_words(candidate)
    pumped_set = {_topic_words(p) for p in used_info.get("pumped", [])}

    for used in used_info.get("used", []):
        used_words = _topic_words(used)
        # Allow if this exact used topic went viral
        if used_words in pumped_set:
            continue
        # Overlap of 3+ meaningful words = same topic
        if len(cand_words & used_words) >= 3:
            return False
    return True


def _pick_fresh_topic(trends, used_info):
    """
    Score all formats by viral potential (viral_angles scores from AI),
    then pick the best FRESH topic from the highest-scoring format.
    Shuffles format order so the same niche isn't always first.
    Returns (topic, format_key) or (None, None).
    """
    from trend_research import get_intelligence_for_format

    ALL_FORMATS = ["story_lesson", "scary_truth", "hidden_psychology"]

    # Score each format by avg viral_score from trend intelligence
    format_scores = {}
    for fmt in ALL_FORMATS:
        intel  = get_intelligence_for_format(fmt)
        angles = intel.get("viral_angles", [])
        if angles:
            avg_score = sum(a.get("viral_score", 50) for a in angles) / len(angles)
        else:
            avg_score = random.uniform(40, 70)   # no data → random so formats rotate
        format_scores[fmt] = avg_score

    # Sort by score descending, but add small random noise to prevent lock-in
    sorted_formats = sorted(
        ALL_FORMATS,
        key=lambda f: format_scores[f] + random.uniform(-10, 10),
        reverse=True,
    )
    print(f"   📊 Format ranking this run: {' > '.join(sorted_formats)}")

    for fmt in sorted_formats:
        intel = get_intelligence_for_format(fmt)
        candidates = []
        best = intel.get("best_topic_right_now", "")
        if best:
            candidates.append(best)
        candidates += intel.get("main_topics", [])[:4]
        candidates += trends.get(fmt, [])

        for topic in candidates:
            if not topic:
                continue
            if _topic_is_fresh(topic, used_info):
                return topic, fmt
            else:
                print(f"   ⚠️  Skipping '{topic[:60]}' — already used")

    return None, None


# ============================================================
# ENSURE FOLDERS
# ============================================================
def ensure_dirs():
    for d in ["images", "clips", "audio", "output", "temp", "fonts"]:
        (BASE_DIR / d).mkdir(exist_ok=True)


# ============================================================
# CLEAN WORKSPACE — wipe all generated files before each run
# Guarantees no stale images/clips/temp from a previous run
# ============================================================
def clean_workspace():
    rules = {
        "images": (".jpg", ".png", ".mp4"),
        "clips":  (".mp4",),
        "temp":   None,          # wipe everything in temp
    }
    total = 0
    for folder, exts in rules.items():
        d = BASE_DIR / folder
        if not d.exists():
            continue
        for f in d.iterdir():
            if not f.is_file():
                continue
            if exts is None or f.suffix.lower() in exts:
                try:
                    f.unlink()
                    total += 1
                except Exception:
                    pass
    print(f"🧹 Workspace clean — {total} old files removed")


# ============================================================
# PIPELINE
# ============================================================
def run_pipeline(manual_idea=None, trend_data=None, viral_followup=False):
    ensure_dirs()
    clean_workspace()    # always start fresh — no stale images/clips/temp

    run_id = int(time.time())
    sep    = "=" * 60

    print(f"\n{sep}")
    print(f"  DARK MIND PIPELINE — Run #{run_id}")
    print(f"{sep}\n")

    # ──────────────────────────────────────────────────────
    # STEP 0: Trend Research
    # Viral follow-ups skip scrape — same topic, new script
    # All other runs always scrape fresh
    # ──────────────────────────────────────────────────────
    trends = {}
    if viral_followup:
        print("🔁 STEP 0/4 — Viral Follow-Up (skipping scrape, same topic)")
    else:
        print("🔍 STEP 0/4 — Trend Research (live scrape)")
        try:
            from trend_research import get_trending_topics, get_intelligence_for_format
            trends = get_trending_topics()   # always fresh — no cache
            if trends:
                print(f"   Trends loaded — {sum(len(v) for v in trends.values())} topics across formats")
        except Exception as e:
            print(f"   ⚠️  Trend research skipped: {e}")

    # If no manual idea — pick best FRESH topic from trend intelligence
    if not manual_idea and not trend_data and trends:
        try:
            from analytics import get_all_used_topics
            used_info = get_all_used_topics()
            if used_info["used"]:
                print(f"   📋 Topics already used: {len(used_info['used'])}  |  Pumped (reusable): {len(used_info['pumped'])}")

            best_idea, best_format = _pick_fresh_topic(trends, used_info)

            if best_idea:
                manual_idea = best_idea
                print(f"   🧠 AI-picked fresh topic: {manual_idea[:80]}")
                print(f"   Format hint: {best_format}")
            else:
                # All known topics used — force a full fresh scrape then try again
                # All live-scraped topics already used — last resort: reuse oldest
                all_topics = [t for v in trends.values() for t in v if t]
                if all_topics:
                    manual_idea = all_topics[0]
                    print(f"   ⚠️  All topics used before — reusing oldest: {manual_idea[:80]}")
        except Exception as exc:
            print(f"   ⚠️  Topic selection error: {exc}")
            all_topics = [t for v in trends.values() for t in v]
            if all_topics:
                trend_data = all_topics[0]
                print(f"   Injecting trend: {trend_data}")

    # ──────────────────────────────────────────────────────
    # STEP 1: Script
    # ──────────────────────────────────────────────────────
    print(f"\n📝 STEP 1/4 — Script")
    from script_writer import generate_script
    from analytics import get_all_used_topics, get_used_hooks

    _used_info   = get_all_used_topics()
    _used_hooks  = get_used_hooks(limit=20)
    _used_topics = _used_info.get("used", [])
    if _used_topics:
        print(f"   🚫 Hook blacklist: {len(_used_hooks)} hooks  |  Topic blacklist: {len(_used_topics)} topics")

    script_data = generate_script(
        trend_data=trend_data,
        manual_idea=manual_idea,
        used_topics=_used_topics,
        used_hooks=_used_hooks,
    )
    if not script_data:
        print("❌ Pipeline stopped: script generation failed")
        return None

    script_path = BASE_DIR / f"temp/script_{run_id}.json"
    script_path.write_text(json.dumps(script_data, indent=2, ensure_ascii=False))
    print(f"💾 Script saved → {script_path.name}")

    word_count = len(script_data.get("script", "").split())
    print(f"📊 Words: {word_count}  |  Format: {script_data.get('format')}  |  Voice: {script_data.get('voice_type')}")
    print(f"🪝 Hook:  {script_data.get('hook_text', 'N/A')}")

    # ──────────────────────────────────────────────────────
    # STEP 2 + 3: Images AND Voiceover — PARALLEL
    # ──────────────────────────────────────────────────────
    print(f"\n🎨🎙️  STEP 2+3/4 — Images & Voiceover (PARALLEL)")

    from image_generator import generate_all_images
    from voiceover import generate_voiceover

    vo_path = str(BASE_DIR / f"audio/voiceover_{run_id}.mp3")
    images  = None
    vo_result = None

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_images = executor.submit(
            generate_all_images,
            script_data,
            str(BASE_DIR / "images"),
            str(BASE_DIR / "clips"),
        )
        future_voice = executor.submit(
            generate_voiceover,
            script_data,
            vo_path,
        )

        for future in as_completed([future_images, future_voice]):
            try:
                if future is future_images:
                    images    = future.result()
                    img_count = len(images) if images else 0
                    print(f"\n   🎨 Images done: {img_count} visuals")
                else:
                    vo_result = future.result()
                    print(f"\n   🎙️  Voiceover done: {vo_result}")
            except Exception as e:
                label = "Images" if future is future_images else "Voiceover"
                print(f"\n   ❌ {label} thread raised exception: {e}")

    if not images:
        print("❌ Pipeline stopped: image generation failed")
        return None
    if not vo_result:
        print("❌ Pipeline stopped: voiceover generation failed")
        return None

    clips_n  = sum(1 for v in images if v["type"] == "clip")
    images_n = sum(1 for v in images if v["type"] == "image")
    print(f"✅ {len(images)} visuals ready ({clips_n} clips, {images_n} images)")

    # ── 60s minimum check — keep regenerating until output is long enough ──
    from assembler import get_audio_duration
    SPEED        = 1.3
    MIN_OUTPUT_S = 60.0
    vo_dur       = get_audio_duration(vo_result)
    _regen_attempt = 0
    while vo_dur / SPEED < MIN_OUTPUT_S and _regen_attempt < 3:
        _regen_attempt += 1
        print(f"\n⚠️  Voiceover {vo_dur:.1f}s → output {vo_dur/SPEED:.1f}s at {SPEED}x — BELOW 60s (attempt {_regen_attempt}/3)")
        print("   Regenerating script with more words...")
        script_data = generate_script(
            trend_data=trend_data,
            manual_idea=script_data.get("topic", manual_idea),
            used_topics=_used_topics,
            used_hooks=_used_hooks + [script_data.get("hook_text", "")],
        )
        if not script_data:
            print("❌ Pipeline stopped: script regeneration failed")
            return None
        _vo_suffix = f"_v{_regen_attempt+1}.mp3"
        vo_result = generate_voiceover(script_data, vo_path.replace(".mp3", _vo_suffix))
        if not vo_result:
            print("❌ Pipeline stopped: voiceover regeneration failed")
            return None
        vo_dur = get_audio_duration(vo_result)
        print(f"   {'✅' if vo_dur/SPEED >= MIN_OUTPUT_S else '⚠️ '} New voiceover: {vo_dur:.1f}s → {vo_dur/SPEED:.1f}s output")

    # ──────────────────────────────────────────────────────
    # STEP 4: Assembly
    # ──────────────────────────────────────────────────────
    print(f"\n🎬 STEP 4/4 — Assembly")
    from assembler import assemble_video

    out_path = str(BASE_DIR / f"output/dark_mind_{run_id}.mp4")
    result   = assemble_video(
        images=images,
        voiceover_path=vo_result,
        script_data=script_data,
        output_path=out_path,
    )

    # ──────────────────────────────────────────────────────
    # ANALYTICS LOG
    # ──────────────────────────────────────────────────────
    if result:
        try:
            from analytics import log_video
            log_video(run_id, script_data, result)
        except Exception as e:
            print(f"   ⚠️  Analytics log failed: {e}")

    # ──────────────────────────────────────────────────────
    # STEP 5: Upload to YouTube + TikTok (parallel)
    # ──────────────────────────────────────────────────────
    yt_id = None
    tt_id = None

    if result and PUBLISH:
        print(f"\n🚀 STEP 5/5 — Publishing")

        def _yt_upload():
            try:
                from uploader_youtube import upload_to_youtube
                return "yt", upload_to_youtube(result, script_data)
            except Exception as e:
                print(f"   ❌ YouTube upload error: {e}")
                return "yt", None

        def _tt_upload():
            try:
                from uploader_tiktok import upload_to_tiktok
                return "tt", upload_to_tiktok(result, script_data)
            except Exception as e:
                print(f"   ❌ TikTok upload error: {e}")
                return "tt", None

        with ThreadPoolExecutor(max_workers=2) as ex:
            futures = [ex.submit(_yt_upload), ex.submit(_tt_upload)]
            for f in as_completed(futures):
                platform, vid_id = f.result()
                if platform == "yt":
                    yt_id = vid_id
                else:
                    tt_id = vid_id

        # Save platform IDs to analytics
        if yt_id or tt_id:
            try:
                from analytics import save_platform_ids
                save_platform_ids(run_id, yt_id, tt_id)
            except Exception as e:
                print(f"   ⚠️  Platform ID save failed: {e}")

        # Fetch stats immediately after posting (gets initial impressions)
        try:
            from stats_fetcher import fetch_and_update_all
            fetch_and_update_all()
        except Exception as e:
            print(f"   ⚠️  Initial stats fetch failed: {e}")

    elif result and not PUBLISH:
        print(f"\n⏸️  STEP 5/5 — Publishing SKIPPED (PUBLISH=False)")

    # ──────────────────────────────────────────────────────
    # SUMMARY
    # ──────────────────────────────────────────────────────
    print(f"\n{sep}")
    if result:
        print(f"  ✅ PIPELINE COMPLETE!")
        print(f"  📹 Output : {result}")
        print(f"  📝 Script : {script_path}")
        print(f"  🎙️  Audio  : {vo_result}")
        if yt_id:
            print(f"  📺 YouTube: https://youtube.com/shorts/{yt_id}")
        if tt_id:
            print(f"  🎵 TikTok : https://www.tiktok.com/@/video/{tt_id}")
    else:
        print(f"  ❌ PIPELINE FAILED at assembly step")
        print(f"  (Script and audio were saved — check temp/ and audio/)")
    print(f"{sep}\n")

    return result


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dark Mind — Video Pipeline")
    parser.add_argument("--idea",  type=str, default=None, help="Manual topic idea")
    parser.add_argument("--trend", type=str, default=None, help="Trending topic context")
    args = parser.parse_args()

    run_pipeline(
        manual_idea=args.idea,
        trend_data=args.trend,
    )

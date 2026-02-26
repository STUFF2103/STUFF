"""
Dark Mind — Video Assembler (v2)
Major changes:
  - Font download: Anton (hook), Montserrat ExtraBold (captions)
  - Dynamic beat timing from pace field (fast/medium/slow)
  - Camera motion from beat's camera_motion field
  - TikTok-style karaoke captions: white chunk + yellow word highlight, ALL CAPS
  - 1.8s hook clip prepended (silent black card with hook_text in Anton font)
  - Pixabay audio API for music (fallback to hardcoded CDN URLs)
  - Whisper "small" model (was "base")
  - Full assembly order with +1.8s offset for all caption timestamps
"""
import os
import re
import sys
import json
import time
import glob
import shutil
import random
import subprocess
import warnings
import requests
import urllib3
from pathlib import Path
from dotenv import load_dotenv

# Suppress SSL warnings from verify=False (ccMixter SSL cert issue on Windows)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

BASE_DIR    = Path(__file__).parent
TEMP_DIR    = BASE_DIR / "temp"
FONTS_DIR   = BASE_DIR / "fonts"
OUTPUT_DIR  = BASE_DIR / "output"

PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY")

# ============================================================
# FONT SETUP — download once, cache locally
# ============================================================
FONT_ANTON       = FONTS_DIR / "Anton-Regular.ttf"
FONT_MONTSERRAT  = FONTS_DIR / "Montserrat-ExtraBold.ttf"

FONT_URLS = {
    "Anton-Regular.ttf": [
        "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf",
        "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
    ],
    # Montserrat ExtraBold — tried multiple paths, use Oswald Bold as reliable alternative
    "Montserrat-ExtraBold.ttf": [
        "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/static/Montserrat-ExtraBold.ttf",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/oswald/static/Oswald-Bold.ttf",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/bebasneue/BebasNeue-Regular.ttf",
    ],
}

# Impact is already on every Windows machine — perfect TikTok caption font, no download needed
IMPACT_FONT = Path("C:/Windows/Fonts/impact.ttf")


def ensure_fonts():
    FONTS_DIR.mkdir(exist_ok=True)
    for fname, urls in FONT_URLS.items():
        dest = FONTS_DIR / fname
        if dest.exists() and dest.stat().st_size > 10_000:   # valid font > 10KB
            continue
        print(f"📥 Downloading font: {fname}...")
        for url in urls:
            try:
                r = requests.get(url, timeout=30)
                if r.status_code == 200 and len(r.content) > 10_000:
                    dest.write_bytes(r.content)
                    print(f"   ✅ {fname} saved ({len(r.content)//1024}KB)")
                    break
                else:
                    print(f"   ⚠️  {url[:60]} → {r.status_code}")
            except Exception as e:
                print(f"   ⚠️  {url[:60]} → {e.__class__.__name__}")
        else:
            if not (dest.exists() and dest.stat().st_size > 10_000):
                print(f"   ❌ Could not download {fname} — captions will use Arial")


def ffmpeg_font_path(font_path):
    """
    Convert a font path to FFmpeg filter-safe string.
    Escapes drive-letter colon for Windows (C: → C\\:).
    """
    p = str(font_path).replace("\\", "/")
    p = p.replace(":", "\\:")
    return p


# ============================================================
# MUSIC LIBRARY — CDN fallback URLs
# NOTE: Pixabay CDN URLs removed — those tracks get registered with HAAWK/Content ID
# and cause YouTube copyright blocks even though they're "free". No CDN fallback;
# if Jamendo + Archive.org both fail the video runs music-free (safer than a strike).
MUSIC_CDN = {}  # intentionally empty — do NOT add Pixabay CDN URLs here

MOOD_QUERIES = {
    "cinematic":   "cinematic dark dramatic",
    "tense":       "tense suspense thriller",
    "dark_ambient":"dark ambient mysterious",
    "phonk":       "phonk dark trap",
    "lofi":        "lofi dark chill",
}

# Track used tracks this session to avoid repeats
_used_music_urls: set = set()


# ============================================================
# CAMERA MOTION MAP (beat-driven)
# ============================================================
MOTION_MAP = {
    "zoom_in":  "zoompan=z='min(zoom+0.002,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={d}:s=1080x1920",
    "zoom_out": "zoompan=z='if(lte(zoom,1.0),1.3,max(1.0,zoom-0.002))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={d}:s=1080x1920",
    "pan_right":"zoompan=z=1.2:x='iw/2-(iw/zoom/2)+20*on/{d}':y='ih/2-(ih/zoom/2)':d={d}:s=1080x1920",
    "pan_left": "zoompan=z=1.2:x='iw/2-(iw/zoom/2)-20*on/{d}':y='ih/2-(ih/zoom/2)':d={d}:s=1080x1920",
    "shake":    "zoompan=z='min(zoom+0.003,1.4)':x='iw/2-(iw/zoom/2)+3*sin(on/2)':y='ih/2-(ih/zoom/2)+3*cos(on/2)':d={d}:s=1080x1920",
}

# Ordered list for random fallback
MOTION_LIST = list(MOTION_MAP.values())

# ============================================================
# CAPTION HIGHLIGHT COLORS — one picked randomly per run
# ============================================================
HIGHLIGHT_COLORS = [
    "#FFE600",  # TikTok yellow
    "#FF3B30",  # hot red
    "#00D4FF",  # electric cyan
    "#FF6B00",  # orange
    "#00FF88",  # lime green
    "#FF2D9B",  # hot pink
]

# ============================================================
# XFADE TRANSITIONS — beat-pace driven
# ============================================================
XFADE_BY_PACE = {
    "fast":   ["fade", "fadeblack", "wipeleft", "wiperight"],
    "medium": ["slideleft", "slideright", "wipeleft", "wiperight"],
    "slow":   ["fade", "fadeblack"],
}
XFADE_DUR = {"fast": 0.12, "medium": 0.18, "slow": 0.25}

# ============================================================
# DYNAMIC TIMING
# ============================================================
PACE_DURATIONS = {"fast": 2.0, "medium": 4.5, "slow": 8.0}


def calculate_beat_durations(visuals, script_data, total_duration):
    """
    Assign each visual a duration proportional to its beat's pace.
    Total always equals total_duration (voiceover length).
    """
    beats    = script_data.get("beats", [])
    beat_map = {b.get("beat"): b for b in beats}

    raw = []
    for vis in visuals:
        beat_num  = vis.get("beat")
        beat_data = beat_map.get(beat_num, {})
        pace      = beat_data.get("pace", "medium")
        raw.append(PACE_DURATIONS.get(pace, 6.5))

    if not raw or sum(raw) == 0:
        uniform = total_duration / max(len(visuals), 1)
        return [uniform] * len(visuals)

    scale = total_duration / sum(raw)
    return [r * scale for r in raw]


def get_beat_camera_motion(vis, script_data):
    """Return the camera_motion string for this visual's beat, or None."""
    beats    = script_data.get("beats", [])
    beat_map = {b.get("beat"): b for b in beats}
    beat_data = beat_map.get(vis.get("beat"), {})
    return beat_data.get("camera_motion")


# ============================================================
# FFMPEG HELPERS
# ============================================================
def run_ffmpeg(cmd, description=""):
    try:
        print(f"⚙️  {description}...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ {description} done")
            return True
        print(f"❌ {description} failed")
        print(result.stderr[-600:] if result.stderr else "No stderr")
        return False
    except Exception as e:
        print(f"❌ FFmpeg exception: {e}")
        return False


def get_audio_duration(path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return 60.0


# ============================================================
# WHISPER — WORD TIMESTAMPS (upgraded to "small" model)
# ============================================================
def get_word_timestamps(audio_path, time_offset=0.0):
    """
    Returns list of {"word", "start", "end"} dicts.
    All timestamps are shifted by time_offset (for hook clip prepend).
    Falls back through model sizes if download fails.
    """
    print("🎯 Running Whisper for word timestamps...")
    try:
        from faster_whisper import WhisperModel
        model = None
        for model_name in ["base", "tiny"]:
            try:
                model = WhisperModel(model_name, device="cpu", compute_type="int8")
                print(f"   Whisper model: {model_name}")
                break
            except Exception as e:
                print(f"   ⚠️  Whisper '{model_name}' failed: {e.__class__.__name__} — trying smaller...")
        if model is None:
            print("❌ Whisper: no model could be loaded")
            return None

        segments, _ = model.transcribe(audio_path, word_timestamps=True, language="en")

        words = []
        for seg in segments:
            if seg.words:
                for wd in seg.words:
                    words.append({
                        "word":  wd.word.strip(),
                        "start": wd.start + time_offset,
                        "end":   wd.end   + time_offset,
                    })
        print(f"✅ Whisper: {len(words)} words timestamped (offset +{time_offset:.1f}s)")
        return words
    except Exception as e:
        print(f"❌ Whisper error: {e}")
        return None


# ============================================================
# TIKTOK-STYLE KARAOKE CAPTIONS
# White chunk (always visible during chunk) + yellow word highlight
# ALL CAPS, 90px, thick black stroke — no box background
# ============================================================
def sanitize_caption(text):
    """Strip chars that break FFmpeg drawtext parser."""
    text = text.upper().strip()
    text = re.sub(r"[\\:'\"\[\]{}|<>]", "", text)
    text = re.sub(r"[!?.,;]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def measure_word_width(word, font_path, font_size=90):
    """Use Pillow to measure pixel width of a word."""
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(str(font_path), font_size)
        return font.getlength(word)
    except Exception:
        # Fallback estimate: ~55px per char at 90px font size
        return len(word) * 55


def measure_space_width(font_path, font_size=90):
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(str(font_path), font_size)
        return font.getlength(" ")
    except Exception:
        return 28


def build_tiktok_captions(word_timestamps, font_path=None, script_data=None, highlight_color=None):
    """
    Build TikTok karaoke caption filters.
    Returns a comma-joined drawtext filter string.
    """
    if not word_timestamps:
        return ""

    # Font priority for measurement (Pillow) and rendering (FFmpeg):
    # 1. Custom font passed in (Montserrat/Oswald if downloaded)
    # 2. Impact — already on Windows, iconic TikTok caption font
    # 3. Arial Bold — safe final fallback
    def _best_font_path():
        if font_path and Path(font_path).exists() and Path(font_path).stat().st_size > 10_000:
            return str(font_path)
        if IMPACT_FONT.exists():
            return str(IMPACT_FONT)
        arial_bold = Path("C:/Windows/Fonts/arialbd.ttf")
        if arial_bold.exists():
            return str(arial_bold)
        return None

    meas_font = _best_font_path()

    # For FFmpeg drawtext: always use fontfile= (no fontstyle= — invalid option)
    if meas_font:
        ffmpeg_font_arg = f"fontfile='{ffmpeg_font_path(meas_font)}'"
    else:
        ffmpeg_font_arg = "font=Arial"   # fontconfig last resort, no style option

    font_size  = 112
    space_w    = measure_space_width(meas_font, font_size) if meas_font else 34
    chunk_size = 3
    filters    = []
    vid_w      = 1080
    y_pos      = "h*0.72"   # Viral TikTok position — upper portion of bottom half
    hl_color   = highlight_color or "#FFE600"

    for ci in range(0, len(word_timestamps), chunk_size):
        chunk       = word_timestamps[ci : ci + chunk_size]
        chunk_start = chunk[0]["start"]
        chunk_end   = chunk[-1]["end"] + 0.1

        # Measure each word
        words_upper = [sanitize_caption(w["word"]) for w in chunk]
        widths      = [measure_word_width(w, meas_font, font_size) for w in words_upper]
        total_w     = sum(widths) + space_w * max(0, len(chunk) - 1)

        start_x     = int((vid_w - total_w) / 2)
        full_text   = " ".join(words_upper)

        # ── White: full chunk visible for entire chunk duration ──
        filters.append(
            f"drawtext={ffmpeg_font_arg}:"
            f"text='{full_text}':"
            f"fontcolor=white:"
            f"fontsize={font_size}:"
            f"x={start_x}:y={y_pos}:"
            f"borderw=6:bordercolor=black:"
            f"enable='between(t,{chunk_start:.3f},{chunk_end:.3f})'"
        )

        # ── Yellow: highlight current word ──
        x = start_x
        for j, word_data in enumerate(chunk):
            word_upper = words_upper[j]
            if not word_upper:
                x += widths[j] + space_w
                continue
            w_start = word_data["start"]
            w_end   = word_data["end"] + 0.05
            filters.append(
                f"drawtext={ffmpeg_font_arg}:"
                f"text='{word_upper}':"
                f"fontcolor={hl_color}:"
                f"fontsize={font_size}:"
                f"x={int(x)}:y={y_pos}:"
                f"borderw=6:bordercolor=black:"
                f"enable='between(t,{w_start:.3f},{w_end:.3f})'"
            )
            x += widths[j] + space_w

    return ",".join(filters)


# ============================================================
# HOOK BACKGROUND — cinematic AI image via Pollinations.ai (free)
# ============================================================
def _generate_hook_background(hook_text):
    """
    Generates the best possible 1080x1920 background for the hook card.

    Tier 1: Wikipedia API — real public-domain photo if hook names a real person/place.
    Tier 2: Leonardo AI  — ultra-detailed cinematic AI art (uses tokens, ~30s).
    Tier 3: Picsum Photos — beautiful random real photo, instantly available.
    Tier 4: PIL gradient  — zero network, always works.

    All tiers apply a dark overlay so the hook text stays readable.
    Returns a PIL Image.
    """
    import io, time as _time
    try:
        from PIL import Image, ImageFilter, ImageEnhance
    except ImportError:
        return None

    def _darken(img, overlay_alpha=0.55, blur=1.0, desaturate=0.3):
        """Apply dark cinematic treatment: desaturate → overlay → blur."""
        img = img.resize((1080, 1920), Image.LANCZOS)
        if desaturate < 1.0:
            img = ImageEnhance.Color(img).enhance(desaturate)
        overlay = Image.new("RGB", (1080, 1920), (0, 0, 0))
        img = Image.blend(img, overlay, alpha=overlay_alpha)
        if blur > 0:
            img = img.filter(ImageFilter.GaussianBlur(radius=blur))
        return img

    # ── Tier 1: Wikimedia Commons — story-contextual, public domain only ──
    # Searches with the hook text so we get images RELATED to the story
    # (e.g. "Tesla laboratory" not just Tesla's portrait, "Disney FBI contract" etc.)
    # All Wikimedia Commons images are public domain or CC — zero copyright risk.
    try:
        # Skip file types that are never photos (svg, gif, ogg, pdf, tif maps etc.)
        _PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".webp")
        _SKIP_WORDS = ("logo", "map", "flag", "icon", "seal", "coat", "symbol",
                       "diagram", "chart", "graph", "signature", "stamp", "svg")

        def _is_good_image(title_or_url):
            t = title_or_url.lower()
            if not any(t.endswith(e) for e in _PHOTO_EXTS):
                return False
            if any(w in t for w in _SKIP_WORDS):
                return False
            return True

        # Extract meaningful search keywords from hook text
        # Remove possessives, filler words, ALL CAPS → clean noun query
        _HOOK_FILLER = {
            "the", "a", "an", "of", "in", "to", "is", "was", "were", "be",
            "dark", "darkest", "shocking", "secret", "secrets", "truth", "exposed",
            "nobody", "talks", "about", "revealed", "hidden", "real", "true",
            "blood", "money", "contract", "never", "told", "untold", "story",
            "what", "how", "why", "who", "this", "that", "and", "or", "but",
            "s", "most", "ever", "you", "your", "they", "their", "his", "her",
        }
        clean_words = []
        for w in hook_text.replace("'S", "").replace("'S", "").split():
            w_clean = w.strip(".,!?\"'").lower()
            if w_clean and w_clean not in _HOOK_FILLER and len(w_clean) > 2:
                clean_words.append(w_clean.capitalize())
        search_query = " ".join(clean_words[:4]) if clean_words else hook_text[:40]

        commons_resp = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action":      "query",
                "list":        "search",
                "srsearch":    search_query,     # cleaned story keywords
                "srnamespace": 6,                # namespace 6 = File (images)
                "srlimit":     20,
                "format":      "json",
            },
            timeout=10,
            headers={"User-Agent": "DarkMindBot/1.0"},
        )
        if commons_resp.status_code == 200:
            results = commons_resp.json().get("query", {}).get("search", [])
            random.shuffle(results)            # vary which image we pick each run
            for item in results:
                title = item.get("title", "")  # e.g. "File:Tesla_lab.jpg"
                if not _is_good_image(title):
                    continue
                # Get the actual image URL via imageinfo
                info_resp = requests.get(
                    "https://commons.wikimedia.org/w/api.php",
                    params={
                        "action": "query",
                        "titles": title,
                        "prop":   "imageinfo",
                        "iiprop": "url|size",
                        "format": "json",
                    },
                    timeout=10,
                    headers={"User-Agent": "DarkMindBot/1.0"},
                )
                if info_resp.status_code != 200:
                    continue
                pages = info_resp.json().get("query", {}).get("pages", {})
                for pg in pages.values():
                    info = pg.get("imageinfo", [{}])[0]
                    img_url = info.get("url", "")
                    width   = info.get("width",  0)
                    height  = info.get("height", 0)
                    # Skip tiny images (less than 300px on either side)
                    if width < 300 or height < 300:
                        continue
                    if not _is_good_image(img_url):
                        continue
                    img_resp = requests.get(img_url, timeout=20,
                                            headers={"User-Agent": "DarkMindBot/1.0"})
                    if img_resp.status_code == 200 and len(img_resp.content) > 15_000:
                        img = Image.open(io.BytesIO(img_resp.content)).convert("RGB")
                        img = _darken(img, overlay_alpha=0.60, blur=1.2, desaturate=0.35)
                        print(f"  Hook background: Wikimedia Commons — {title[5:45]}")
                        return img
    except Exception as e:
        print(f"  Wikimedia Commons hook: {e.__class__.__name__}")

    # ── Tier 2: Leonardo AI — ultra-detailed cinematic art ───────────────
    _leo_keys = [k for k in [
        os.getenv("LEONARDO_API_KEY_1"),
        os.getenv("LEONARDO_API_KEY_2"),
        os.getenv("LEONARDO_API_KEY_3"),
    ] if k]

    for key in _leo_keys:
        try:
            chk    = requests.get("https://cloud.leonardo.ai/api/rest/v1/me",
                                  headers={"Authorization": f"Bearer {key}"}, timeout=10)
            tokens = chk.json().get("user_details",[{}])[0].get("subscriptionTokens",0) if chk.status_code==200 else 0
            if tokens < 5:
                continue

            prompt = (
                f"ultra dramatic cinematic scene: {hook_text}. "
                "extreme close-up, face half-submerged in deep shadow, "
                "single cold harsh light from below casting upward shadows, "
                "hollow eyes filled with dread, film noir chiaroscuro, "
                "dark atmospheric, fog wisps, deep blacks, photorealistic, "
                "8K, vertical 9:16, anamorphic lens flare, subtle film grain, "
                "shallow depth of field, no text, no words, no watermarks"
            )
            resp = requests.post(
                "https://cloud.leonardo.ai/api/rest/v1/generations",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"prompt": prompt,
                      "negative_prompt": "bright colors, cheerful, cartoon, text, watermark, blurry",
                      "width": 576, "height": 1024, "num_images": 1,
                      "guidance_scale": 8, "num_inference_steps": 20},
                timeout=30,
            )
            if resp.status_code != 200:
                continue
            gen_id = resp.json().get("sdGenerationJob", {}).get("generationId")
            if not gen_id:
                continue

            print(f"  Hook background: Leonardo AI generating ({tokens} tokens)...")
            for _ in range(12):
                _time.sleep(5)
                poll = requests.get(
                    f"https://cloud.leonardo.ai/api/rest/v1/generations/{gen_id}",
                    headers={"Authorization": f"Bearer {key}"}, timeout=20)
                if poll.status_code == 200:
                    imgs = poll.json().get("generations_by_pk", {}).get("generated_images", [])
                    if imgs:
                        img_resp = requests.get(imgs[0]["url"], timeout=30)
                        if img_resp.status_code == 200:
                            img = Image.open(io.BytesIO(img_resp.content)).convert("RGB")
                            img = _darken(img, overlay_alpha=0.45, blur=0.8, desaturate=0.8)
                            print("  Hook background: Leonardo AI ready")
                            return img
        except Exception as e:
            print(f"  Leonardo hook error: {e.__class__.__name__}")
            continue

    # ── Tier 3: Picsum Photos — beautiful real photo, always available ────
    try:
        seed = sum(ord(c) for c in hook_text) % 1000
        r    = requests.get(f"https://picsum.photos/seed/{seed}/1080/1920",
                            timeout=20, headers={"User-Agent": "Mozilla/5.0"},
                            allow_redirects=True)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        img = _darken(img, overlay_alpha=0.65, blur=1.5, desaturate=0.25)
        print("  Hook background: Picsum photo")
        return img
    except Exception as e:
        print(f"  Picsum failed ({e.__class__.__name__})")

    # ── Tier 4: PIL gradient — zero network, always works ────────────────
    img    = Image.new("RGB", (1080, 1920))
    px     = img.load()
    for y in range(1920):
        t = y / 1920
        for x in range(1080):
            px[x, y] = (int(5 + 10*(1-t)), int(5 + 15*(1-t)), int(20 + 25*(1-t)))
    return img


# ============================================================
# HOOK CLIP — 1.8s cinematic card with hook_text in Anton font
# ============================================================
def make_hook_clip(hook_text, duration=1.8, output_dir=None):
    """
    Creates a 1.8s black card MP4 with hook_text rendered via Pillow.
    Returns path to hook_clip.mp4 or None on failure.
    """
    if not hook_text:
        return None

    out_dir  = Path(output_dir) if output_dir else TEMP_DIR
    out_dir.mkdir(exist_ok=True)
    png_path = str(out_dir / "hook_card.png")
    mp4_path = str(out_dir / "hook_clip.mp4")

    try:
        from PIL import Image, ImageDraw, ImageFont

        # ── Generate cinematic background via Pollinations.ai (free, no key) ──
        img = _generate_hook_background(hook_text)
        if img is None:
            img = Image.new("RGB", (1080, 1920), color=(0, 0, 0))

        draw = ImageDraw.Draw(img)

        # Load Anton if available, else fall back to Arial Bold
        if FONT_ANTON.exists():
            font = ImageFont.truetype(str(FONT_ANTON), 110)
        else:
            try:
                font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 110)
            except Exception:
                font = ImageFont.load_default()

        text = hook_text.upper()

        # Word-wrap at ~900px wide
        words   = text.split()
        lines   = []
        current = []
        for word in words:
            test_line = " ".join(current + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] > 940 and current:
                lines.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            lines.append(" ".join(current))

        line_h  = 135
        total_h = len(lines) * line_h
        y_start = (1920 - total_h) // 2 - 60

        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            lw   = bbox[2] - bbox[0]
            x    = (1080 - lw) // 2
            y    = y_start + i * line_h
            # Thick black outline
            for dx, dy in [(-4,-4),(4,-4),(-4,4),(4,4),(0,-5),(0,5),(-5,0),(5,0)]:
                draw.text((x+dx, y+dy), line, font=font, fill=(0, 0, 0))
            # White fill
            draw.text((x, y), line, font=font, fill=(255, 255, 255))

        img.save(png_path)

    except Exception as e:
        print(f"⚠️  Hook card Pillow error: {e}")
        return None

    # Convert PNG to video — use -framerate + -frames:v for Linux ffmpeg compatibility
    frames = max(1, int(duration * 30))
    success = run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-framerate", "30",
            "-loop", "1", "-i", png_path,
            "-c:v", "libx264",
            "-frames:v", str(frames),
            "-r", "30",
            "-pix_fmt", "yuv420p",
            "-vf", "scale=1080:1920:force_original_aspect_ratio=disable",
            "-an",
            mp4_path,
        ],
        "Hook clip"
    )
    return mp4_path if success and os.path.exists(mp4_path) else None


# ============================================================
# MUSIC — Pixabay API first, CDN fallback
# ============================================================
def _is_valid_audio(file_path):
    """Return True only if ffprobe finds at least one audio stream."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(file_path)],
            capture_output=True, text=True,
        )
        return "audio" in result.stdout
    except Exception:
        return False


def fetch_music_track(mood, output_path="temp/music.mp3"):
    global _used_music_urls
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept":     "audio/mpeg, audio/*, */*",
    }

    JAMENDO_TAGS = {
        "cinematic":   "epic cinematic orchestral",
        "tense":       "thriller suspense dark",
        "dark_ambient":"dark ambient mysterious",
        "phonk":       "dark hip-hop trap",
        "lofi":        "lofi ambient chill",
    }

    def _download(url, label):
        try:
            r = requests.get(url, headers=headers, timeout=35, stream=True)
            if r.status_code == 200:
                content = b"".join(r.iter_content(65536))
                if len(content) > 30_000:
                    with open(output_path, "wb") as f:
                        f.write(content)
                    if _is_valid_audio(output_path):
                        _used_music_urls.add(url)
                        print(f"✅ Music {label}: {len(content)//1024}KB")
                        return True
        except Exception:
            pass
        return False

    # ── Tier 1: ccMixter (CC-BY — safe for YouTube/TikTok) ──────────────────
    CCMIXTER_TAGS = {
        "cinematic":    "cinematic",
        "tense":        "dark",
        "dark_ambient": "ambient",
        "phonk":        "hip+hop",
        "lofi":         "chill",
    }
    ccm_tag = CCMIXTER_TAGS.get(mood, "dark")
    try:
        resp = requests.get(
            "http://ccmixter.org/api/query",
            params={"tags": ccm_tag, "limit": 20, "format": "json", "type": "track"},
            timeout=15,
        )
        if resp.status_code == 200:
            tracks = resp.json()
            random.shuffle(tracks)
            for track in tracks:
                for f in track.get("files", []):
                    # Use the download_url field directly — most reliable
                    audio_url = f.get("download_url", "")
                    if not audio_url or not audio_url.endswith(".mp3"):
                        continue
                    if audio_url in _used_music_urls:
                        continue
                    label = f"ccMixter/{track.get('upload_name','')[:25]}"
                    # verify=False needed for ccMixter SSL cert on Windows Python 3.14
                    try:
                        r = requests.get(audio_url, headers=headers, timeout=35,
                                         stream=True, verify=False)
                        if r.status_code == 200:
                            content = b"".join(r.iter_content(65536))
                            if len(content) > 30_000:
                                with open(output_path, "wb") as f_out:
                                    f_out.write(content)
                                if _is_valid_audio(output_path):
                                    _used_music_urls.add(audio_url)
                                    print(f"✅ Music {label}: {len(content)//1024}KB")
                                    return output_path
                    except Exception:
                        continue
    except Exception as e:
        print(f"   ⚠️  ccMixter music error: {e}")

    # ── Tier 2: Archive.org (CC music, stable) ───────────────
    ARCHIVE_QUERIES = {
        "cinematic":   "dark cinematic orchestral",
        "tense":       "suspense tense thriller",
        "dark_ambient":"dark ambient instrumental",
        "phonk":       "dark trap instrumental",
        "lofi":        "lo-fi dark chill instrumental",
    }
    archive_q = ARCHIVE_QUERIES.get(mood, "dark cinematic instrumental")
    try:
        search_resp = requests.get(
            "https://archive.org/advancedsearch.php",
            params={
                "q":      f"({archive_q}) AND mediatype:audio AND licenseurl:*creative*",
                "output": "json",
                "rows":   15,
                "fields": "identifier",
            },
            timeout=12,
        )
        if search_resp.status_code == 200:
            docs = search_resp.json().get("response", {}).get("docs", [])
            random.shuffle(docs)
            for doc in docs[:6]:
                iid = doc.get("identifier", "")
                if not iid:
                    continue
                try:
                    meta = requests.get(
                        f"https://archive.org/metadata/{iid}/files", timeout=8
                    ).json().get("result", [])
                    mp3s = [f for f in meta if f.get("format") in ("MP3", "VBR MP3")
                            and int(f.get("length", 0) or 0) > 30]
                    random.shuffle(mp3s)
                    for mp3 in mp3s[:2]:
                        dl_url = f"https://archive.org/download/{iid}/{mp3['name']}"
                        if dl_url in _used_music_urls:
                            continue
                        if _download(dl_url, f"archive.org/{iid[:20]}"):
                            return output_path
                except Exception:
                    continue
    except Exception as e:
        print(f"   ⚠️  Archive.org music error: {e}")

    # ── Tier 3: CDN fallback (disabled — Pixabay tracks trigger Content ID) ─
    # MUSIC_CDN is intentionally empty; video runs music-free rather than risk
    # a YouTube copyright block like "Lofi Study - FASSounds / HAAWK".
    print("⚠️  Music unavailable — video will be voice-only (safer than a copyright strike)")
    return None


# ============================================================
# KEN BURNS WITH BEAT-DRIVEN CAMERA MOTION
# ============================================================
def apply_ken_burns(image_path, duration, index, camera_motion=None):
    output = str(TEMP_DIR / f"kb_{index}.mp4")
    fps    = 30
    frames = max(1, int(duration * fps))   # exact frames, no +0.1 drift

    if camera_motion and camera_motion in MOTION_MAP:
        effect = MOTION_MAP[camera_motion].format(d=frames)
    else:
        effect = random.choice(MOTION_LIST).format(d=frames)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-vf", (
            "scale=1440:2560:force_original_aspect_ratio=increase,"
            "crop=1440:2560,"
            f"{effect},"
            f"fps={fps}"
        ),
        "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an",
        output,
    ]
    return output if run_ffmpeg(cmd, f"Ken Burns beat {index} [{camera_motion or 'random'}]") else None


# ============================================================
# PROCESS VIDEO CLIP
# ============================================================
def process_video_clip(clip_path, duration, index):
    output = str(TEMP_DIR / f"clip_{index}.mp4")
    frames = max(1, int(duration * 30))
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",         # loop clip if shorter than requested duration
        "-i", clip_path,
        "-vf", (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            "fps=30"                   # CFR output — fps filter at end avoids vsync conflict
        ),
        "-frames:v", str(frames),     # exact frame count (replaces -t to avoid vsync issues)
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-an",
        output,
    ]
    return output if run_ffmpeg(cmd, f"Clip beat {index}") else None


# ============================================================
# BUILD VISUAL LIST FROM DIRS (legacy helper — used when images=None)
# ============================================================
def build_visual_list(images_dir="images", clips_dir="clips", format_key="story_lesson"):
    images = sorted(glob.glob(f"{images_dir}/*.jpg") + glob.glob(f"{images_dir}/*.png"))
    clips  = sorted(glob.glob(f"{clips_dir}/*.mp4"))
    if not images and not clips:
        return []
    ratio      = {"story_lesson": 0.3, "scary_truth": 0.4, "hidden_psychology": 0.2}.get(format_key, 0.3)
    clips_per  = max(1, round(1 / ratio)) if ratio > 0 else 999
    combined   = []
    ci         = 0
    for i, img in enumerate(images):
        combined.append({"path": img, "type": "image"})
        if (i + 1) % clips_per == 0 and ci < len(clips):
            combined.append({"path": clips[ci], "type": "clip"})
            ci += 1
    while ci < len(clips):
        combined.append({"path": clips[ci], "type": "clip"})
        ci += 1
    return combined


# ============================================================
# XFADE CONCAT — beat-aware transitions between every clip
# ============================================================
def concat_with_xfade(clip_paths, durations, script_data=None):
    """
    Concatenate clips with smooth xfade transitions driven by beat pace.
    fast beats  → hard snap (0.08s fadeblack/wipe)
    medium beats → dynamic slide (0.12s)
    slow beats  → smooth fade (0.15s)
    """
    output = str(TEMP_DIR / "concat.mp4")

    if not clip_paths:
        return None
    if len(clip_paths) == 1:
        shutil.copy(clip_paths[0], output)
        return output

    beats    = script_data.get("beats", []) if script_data else []
    # beats[0] corresponds to the FIRST beat clip (index may be offset by hook card)
    # We match by position — first clip in list = first beat reference
    n = len(clip_paths)

    cmd = ["ffmpeg", "-y"]
    for p in clip_paths:
        cmd += ["-i", p]

    filters        = []
    prev_label     = "[0:v]"
    cum_offset     = 0.0

    for i in range(n - 1):
        # Beat index: hook card has no beat, so offset by 1 if present
        beat_idx = i if i < len(beats) else len(beats) - 1
        pace     = beats[beat_idx].get("pace", "medium") if beats else "medium"

        tdur     = XFADE_DUR.get(pace, 0.1)
        trans    = random.choice(XFADE_BY_PACE.get(pace, ["fade"]))

        cum_offset += durations[i] - tdur
        out_label   = f"[xv{i+1}]" if i < n - 2 else "[vout]"

        filters.append(
            f"{prev_label}[{i+1}:v]xfade=transition={trans}:"
            f"duration={tdur:.3f}:offset={max(0.01, cum_offset):.3f}{out_label}"
        )
        prev_label = f"[xv{i+1}]"

    cmd += [
        "-filter_complex", ";".join(filters),
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-r", "30", "-pix_fmt", "yuv420p", "-an", output,
    ]
    return output if run_ffmpeg(cmd, "Concat with xfade transitions") else None


# ============================================================
# MAIN ASSEMBLER
# ============================================================
def assemble_video(
    images=None,
    voiceover_path="audio/voiceover.mp3",
    script_data=None,
    output_path=None,
    images_dir="images",
    clips_dir="clips",
):
    if script_data is None:
        script_data = {}

    TEMP_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    ensure_fonts()

    if output_path is None:
        output_path = str(OUTPUT_DIR / f"dark_mind_{int(time.time())}.mp4")

    print(f"\n🎬 Assembling: {output_path}")

    # ── Pick random highlight color for captions this run ─
    highlight_color = random.choice(HIGHLIGHT_COLORS)
    print(f"🎨 Caption highlight: {highlight_color}")

    # ── 1. Voiceover duration ──────────────────────────────
    vo_duration    = get_audio_duration(voiceover_path)
    total_duration = vo_duration          # hook is spoken, no silent padding
    print(f"⏱️  Voiceover: {vo_duration:.2f}s")

    # ── 2. Hook clip — visual backdrop while voice speaks hook ──
    HOOK_DURATION = 1.8
    hook_text     = script_data.get("hook_text", "")
    hook_clip     = make_hook_clip(hook_text, HOOK_DURATION, str(TEMP_DIR)) if hook_text else None
    if hook_clip:
        print(f"🪝 Hook card: {HOOK_DURATION}s visual — voice starts at t=0 speaking '{hook_text}'")

    # ── 3. Whisper word timestamps — no offset, voice at t=0 ──
    word_timestamps = get_word_timestamps(voiceover_path, time_offset=0.0)

    # ── 4. Music ──────────────────────────────────────────
    _raw_mood    = script_data.get("suggested_music", "cinematic")
    _valid_moods = {"cinematic", "tense", "dark_ambient", "phonk", "lofi"}
    mood = _raw_mood if _raw_mood in _valid_moods else next(
        (c for c in re.split(r"[\s,/]+", _raw_mood) if c in _valid_moods), "cinematic"
    )
    music_path = fetch_music_track(mood, str(TEMP_DIR / "music.mp3"))

    # ── 5. Build / normalise visual list ──────────────────
    if images is None:
        format_key = script_data.get("format", "story_lesson")
        images     = build_visual_list(images_dir, clips_dir, format_key)

    if not images:
        print("❌ No visuals found — aborting")
        return None

    visuals = []
    for item in images:
        if isinstance(item, str):
            visuals.append({"path": item, "type": "clip" if item.endswith(".mp4") else "image"})
        else:
            visuals.append(item)
    visuals = [v for v in visuals if v.get("path") and os.path.exists(v["path"])]

    if not visuals:
        print("❌ None of the visual files exist on disk — aborting")
        return None

    print(f"🎥 Visuals: {len(visuals)} ({sum(1 for v in visuals if v['type']=='image')} images, {sum(1 for v in visuals if v['type']=='clip')} clips)")

    # ── 6. Dynamic durations — beat clips fill (vo - hook) time ──
    visual_duration = vo_duration - (HOOK_DURATION if hook_clip else 0.0)
    durations = calculate_beat_durations(visuals, script_data, max(visual_duration, vo_duration / len(visuals)))
    print(f"⚡ Beat durations: {[f'{d:.1f}s' for d in durations]}")

    # ── 7. Process each visual with beat camera motion ────
    processed = []
    for i, vis in enumerate(visuals):
        dur    = durations[i] if i < len(durations) else visual_duration / len(visuals)
        motion = get_beat_camera_motion(vis, script_data)

        if vis["type"] == "clip":
            out = process_video_clip(vis["path"], dur, i + 1)
        else:
            out = apply_ken_burns(vis["path"], dur, i + 1, camera_motion=motion)
        if out:
            processed.append(out)

    if not processed:
        print("❌ No visuals processed successfully")
        return None

    # ── 7b. Prepend hook card (visual only, voice already speaking) ──
    if hook_clip:
        processed      = [hook_clip] + processed
        hook_durations = [HOOK_DURATION] + durations
    else:
        hook_durations = durations

    # ── 8. Concat with xfade transitions ──────────────────
    concat_path = concat_with_xfade(processed, hook_durations, script_data)
    if not concat_path:
        # Fallback to simple concat if xfade fails
        print("⚠️  xfade failed — falling back to simple concat")
        concat_file = str(TEMP_DIR / "concat.txt")
        with open(concat_file, "w") as f:
            for p in processed:
                f.write(f"file '{os.path.abspath(p)}'\n")
        concat_path = str(TEMP_DIR / "concat.mp4")
        ok = run_ffmpeg(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", concat_file,
             "-c:v", "libx264", "-preset", "fast", "-crf", "23",
             "-r", "30", "-an", concat_path],
            "Simple concat fallback",
        )
        if not ok:
            return None

    # ── 9. Dark color grade ───────────────────────────────
    graded_path = str(TEMP_DIR / "graded.mp4")
    run_ffmpeg(
        ["ffmpeg", "-y", "-i", concat_path,
         "-vf", "eq=contrast=1.15:brightness=-0.05:saturation=0.85,curves=preset=darker,vignette=PI/4",
         "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-an", graded_path],
        "Dark color grade",
    )

    # ── 10. TikTok karaoke captions ───────────────────────
    captioned_path  = os.path.abspath(str(TEMP_DIR / "captioned.mp4"))
    caption_filter  = ""
    if word_timestamps:
        caption_filter = build_tiktok_captions(
            word_timestamps,
            font_path=str(FONT_MONTSERRAT) if FONT_MONTSERRAT.exists() else None,
            script_data=script_data,
            highlight_color=highlight_color,
        )

    if caption_filter:
        filter_script = os.path.abspath(str(TEMP_DIR / "caption_filter.txt"))
        with open(filter_script, "w", encoding="utf-8") as fh:
            fh.write(caption_filter)

        ok = run_ffmpeg(
            ["ffmpeg", "-y",
             "-i", os.path.abspath(graded_path),
             "-filter_script:v", filter_script,
             "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-an",
             captioned_path],
            "TikTok karaoke captions",
        )
        if not ok:
            print("⚠️  Custom font failed — retrying with Arial")
            fallback_filter = build_tiktok_captions(
                word_timestamps, font_path=None, script_data=script_data,
                highlight_color=highlight_color,
            )
            with open(filter_script, "w", encoding="utf-8") as fh:
                fh.write(fallback_filter)
            ok2 = run_ffmpeg(
                ["ffmpeg", "-y",
                 "-i", os.path.abspath(graded_path),
                 "-filter_script:v", filter_script,
                 "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-an",
                 captioned_path],
                "TikTok captions (Arial fallback)",
            )
            if not ok2:
                shutil.copy(graded_path, captioned_path)
    else:
        print("⚠️  No caption data — skipping captions")
        shutil.copy(graded_path, captioned_path)

    # ── 11. Final mix: video + voiceover (t=0) + music ───
    # Voice starts at t=0 — hook text is SPOKEN, not silent
    voice_filter = "[1:a]volume=1.0[voice]"

    if music_path and os.path.exists(music_path):
        filter_complex = (
            f"[0:v]trim=duration={total_duration:.3f},setpts=PTS-STARTPTS[v];"
            f"{voice_filter};"
            f"[2:a]volume=0.08,atrim=duration={total_duration:.3f},asetpts=PTS-STARTPTS[music];"
            f"[voice][music]amix=inputs=2:duration=first[audio]"
        )
        final_cmd = [
            "ffmpeg", "-y",
            "-i", captioned_path,
            "-i", voiceover_path,
            "-i", music_path,
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[audio]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(total_duration),
            output_path,
        ]
    else:
        filter_complex = (
            f"[0:v]trim=duration={total_duration:.3f},setpts=PTS-STARTPTS[v];"
            f"{voice_filter}"
        )
        final_cmd = [
            "ffmpeg", "-y",
            "-i", captioned_path,
            "-i", voiceover_path,
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[voice]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(total_duration),
            output_path,
        ]

    run_ffmpeg(final_cmd, "Final mix (video + voice + music)")

    # ── Speed up final video ──────────────────────────────
    PLAYBACK_SPEED = 1.3
    if os.path.exists(output_path):
        sped_path = output_path.replace(".mp4", "_fast.mp4")
        atempo    = PLAYBACK_SPEED
        speed_ok  = run_ffmpeg(
            [
                "ffmpeg", "-y", "-i", output_path,
                "-filter_complex",
                f"[0:v]setpts=PTS/{atempo}[v];[0:a]atempo={atempo}[a]",
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                "-c:a", "aac", "-b:a", "192k",
                sped_path,
            ],
            f"Speed up {atempo}x",
        )
        if speed_ok and os.path.exists(sped_path):
            # Windows can hold a file lock briefly after FFmpeg exits — retry a few times
            for _attempt in range(5):
                try:
                    if os.path.exists(output_path):
                        os.remove(output_path)
                    shutil.move(sped_path, output_path)
                    break
                except PermissionError:
                    time.sleep(1)

    # ── Report ────────────────────────────────────────────
    if os.path.exists(output_path):
        size_mb    = os.path.getsize(output_path) / (1024 * 1024)
        actual_dur = get_audio_duration(output_path)
        orig_dur   = total_duration
        print(f"\n🎉 VIDEO READY!")
        print(f"   📁 File      : {output_path}")
        print(f"   📦 Size      : {size_mb:.1f} MB")
        print(f"   ⏱️  Duration  : {actual_dur:.2f}s  (original {orig_dur:.1f}s, sped up {PLAYBACK_SPEED}x)")
        return output_path
    else:
        print("❌ Final assembly failed — output file not created")
        return None


# ============================================================
# TEST
# ============================================================
if __name__ == "__main__":
    ensure_fonts()
    visuals = build_visual_list("images", "clips", "story_lesson")
    print(f"Visuals found: {len(visuals)}")

    vo = "test_voiceover.mp3"
    if not os.path.exists(vo):
        print(f"❌ No voiceover at {vo}")
    elif not visuals:
        print("❌ No visuals in images/ or clips/")
    else:
        test_script = {
            "format":         "story_lesson",
            "suggested_music":"cinematic",
            "hook_text":      "THIS TRADER LOST $420K IN 4 MINUTES",
        }
        assemble_video(
            images=visuals,
            voiceover_path=vo,
            script_data=test_script,
            output_path="output/test_output.mp4",
        )

"""
Dark Mind — Image & Clip Generator
- visual_type field (from beat) drives image vs clip decision (replaces odd/even)
- adaptive_darken() applied to ALL Pexels/Pixabay fallback photos
- Leonardo AI → Pexels photo → Pixabay photo (images)
- Pexels video → Pixabay video (clips)
"""
import os
import sys
import time
import random
import requests
from pathlib import Path
from dotenv import load_dotenv

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

LEONARDO_KEYS = [
    os.getenv("LEONARDO_API_KEY_1"),
    os.getenv("LEONARDO_API_KEY_2"),
    os.getenv("LEONARDO_API_KEY_3"),
]
LEONARDO_KEYS   = [k for k in LEONARDO_KEYS if k]
PEXELS_API_KEY  = os.getenv("PEXELS_API_KEY")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY")

current_key_index = 0

# Track used video keywords per run — prevents duplicate Pexels searches
_used_keywords: set = set()

# Suffixes to vary duplicate keywords so each beat gets different search results
_KW_VARIATIONS = [
    "close up", "wide angle", "aerial view", "slow motion",
    "night scene", "dramatic light", "silhouette", "interior",
    "exterior", "detail shot",
]

# ============================================================
# STYLE PRESETS
# ============================================================
STYLE_PROMPTS = {
    "dark_luxury":   "dark cinematic luxury aesthetic, dramatic shadows, deep blacks, golden accents, photorealistic, 4k, vertical",
    "dark_horror":   "dark atmospheric horror, eerie lighting, fog, shadows, cinematic, unsettling, photorealistic, vertical",
    "abstract_dark": "dark abstract digital art, particle effects, neon traces, mysterious, deep space atmosphere, vertical",
    "dark_cinematic":"dark cinematic scene, dramatic lighting, film noir, high contrast, photorealistic, 4k, vertical",
    "illustrated":   "digital illustration, graphic novel style, dark colors, dramatic composition, detailed, vertical",
}

FORMATS_VISUAL = {
    "story_lesson":      "dark_luxury",
    "scary_truth":       "dark_horror",
    "hidden_psychology": "abstract_dark",
}


# ============================================================
# ADAPTIVE DARKENING — applied to ALL fallback photos
# ============================================================
def adaptive_darken(image_path):
    """
    Darken a Pexels/Pixabay photo to match the dark cinematic aesthetic.
    Treatment strength adapts to the image's current brightness.
    """
    try:
        from PIL import Image, ImageEnhance
        img = Image.open(image_path).convert("RGB")

        # Measure average brightness (0-255)
        brightness = sum(img.convert("L").getdata()) / (img.width * img.height)

        if brightness > 180:          # Very bright → heavy treatment
            contrast_val  = 1.4
            bright_factor = 0.35
            saturation    = 0.5
        elif brightness > 120:        # Medium → moderate treatment
            contrast_val  = 1.25
            bright_factor = 0.55
            saturation    = 0.65
        else:                         # Already dark → light touch
            contrast_val  = 1.1
            bright_factor = 0.8
            saturation    = 0.8

        img = ImageEnhance.Contrast(img).enhance(contrast_val)
        img = ImageEnhance.Brightness(img).enhance(bright_factor)
        img = ImageEnhance.Color(img).enhance(saturation)
        img.save(image_path, quality=95)
        return image_path
    except Exception as e:
        print(f"  ⚠️  adaptive_darken failed: {e}")
        return image_path


# ============================================================
# LEONARDO KEY MANAGEMENT
# ============================================================
def get_leonardo_key():
    global current_key_index
    if not LEONARDO_KEYS:
        return None
    return LEONARDO_KEYS[current_key_index % len(LEONARDO_KEYS)]


def rotate_key():
    global current_key_index
    current_key_index += 1
    idx = (current_key_index % len(LEONARDO_KEYS)) + 1 if LEONARDO_KEYS else 0
    print(f"  🔄 Rotating to Leonardo key {idx}")


def check_leonardo_tokens(key):
    try:
        r = requests.get(
            "https://cloud.leonardo.ai/api/rest/v1/me",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("user_details", [{}])[0].get("subscriptionTokens", 0)
        return 0
    except Exception:
        return 0


# ============================================================
# LEONARDO AI GENERATION
# ============================================================
def generate_leonardo(prompt, style, index, output_dir):
    global current_key_index
    for _ in range(len(LEONARDO_KEYS)):
        key = get_leonardo_key()
        if not key:
            return None

        tokens = check_leonardo_tokens(key)
        if tokens < 5:
            print(f"  ⚠️  Key {(current_key_index % len(LEONARDO_KEYS))+1} low ({tokens} tokens) — rotating")
            rotate_key()
            continue

        try:
            style_suffix = STYLE_PROMPTS.get(style, STYLE_PROMPTS["dark_cinematic"])
            full_prompt  = f"{prompt}, {style_suffix}"

            resp = requests.post(
                "https://cloud.leonardo.ai/api/rest/v1/generations",
                headers={
                    "Authorization":  f"Bearer {key}",
                    "Content-Type":   "application/json",
                },
                json={
                    "prompt":           full_prompt,
                    "negative_prompt":  "watermark, text, logo, blurry, bad quality, bright colors, happy, cheerful",
                    "width":            576,
                    "height":           1024,
                    "num_images":       1,
                    "guidance_scale":   7,
                    "num_inference_steps": 15,
                },
                timeout=30,
            )

            if resp.status_code == 200:
                gen_id = resp.json().get("sdGenerationJob", {}).get("generationId")
                if not gen_id:
                    rotate_key()
                    continue

                for _ in range(12):
                    time.sleep(5)
                    poll = requests.get(
                        f"https://cloud.leonardo.ai/api/rest/v1/generations/{gen_id}",
                        headers={"Authorization": f"Bearer {key}"},
                        timeout=30,
                    )
                    if poll.status_code == 200:
                        imgs = poll.json().get("generations_by_pk", {}).get("generated_images", [])
                        if imgs:
                            img_resp = requests.get(imgs[0]["url"], timeout=30)
                            if img_resp.status_code == 200:
                                out = os.path.join(output_dir, f"beat_{index:02d}_leonardo.jpg")
                                with open(out, "wb") as f:
                                    f.write(img_resp.content)
                                print(f"  ✅ Leonardo key {(current_key_index % len(LEONARDO_KEYS))+1}: beat {index} ({tokens} tokens left)")
                                return out
                rotate_key()

            elif resp.status_code == 429:
                print(f"  ⚠️  Rate limit key {(current_key_index % len(LEONARDO_KEYS))+1} — rotating")
                rotate_key()
            else:
                print(f"  ❌ Leonardo error: {resp.status_code}")
                rotate_key()

        except Exception as e:
            print(f"  ❌ Leonardo exception: {e}")
            rotate_key()

    return None


# ============================================================
# PEXELS PHOTO FALLBACK (with adaptive darkening)
# ============================================================
def get_pexels_fallback(prompt, index, output_dir):
    try:
        query = " ".join(prompt.split()[:5])
        page  = random.randint(1, 4)
        resp  = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": query, "per_page": 15, "orientation": "portrait", "page": page},
        )
        if resp.status_code == 200:
            photos = resp.json().get("photos", [])
            if photos:
                img_url  = random.choice(photos)["src"]["large2x"]
                img_resp = requests.get(img_url, timeout=30)
                if img_resp.status_code == 200:
                    out = os.path.join(output_dir, f"beat_{index:02d}_pexels.jpg")
                    with open(out, "wb") as f:
                        f.write(img_resp.content)
                    adaptive_darken(out)
                    print(f"  ✅ Pexels photo beat {index} (darkened)")
                    return out
        return None
    except Exception as e:
        print(f"  ❌ Pexels photo error: {e}")
        return None


# ============================================================
# PIXABAY PHOTO FALLBACK (with adaptive darkening)
# ============================================================
def get_pixabay_fallback(prompt, index, output_dir):
    try:
        query = "+".join(prompt.split()[:3])
        resp  = requests.get(
            "https://pixabay.com/api/",
            params={
                "key":        PIXABAY_API_KEY,
                "q":          query,
                "per_page":   10,
                "orientation":"vertical",
                "image_type": "photo",
            },
        )
        if resp.status_code == 200:
            hits = resp.json().get("hits", [])
            if hits:
                img_url  = random.choice(hits).get("largeImageURL", "")
                img_resp = requests.get(img_url, timeout=30)
                if img_resp.status_code == 200:
                    out = os.path.join(output_dir, f"beat_{index:02d}_pixabay.jpg")
                    with open(out, "wb") as f:
                        f.write(img_resp.content)
                    adaptive_darken(out)
                    print(f"  ✅ Pixabay photo beat {index} (darkened)")
                    return out
        return None
    except Exception as e:
        print(f"  ❌ Pixabay photo error: {e}")
        return None


# ============================================================
# GAMING CLIP FALLBACK — safe background footage for YouTube/TikTok
# Used when no relevant clip exists for a beat's keywords
# ============================================================
GAMING_QUERIES = [
    "subway surfers mobile game",
    "minecraft parkour gameplay",
    "satisfying mobile game",
    "temple run gameplay",
    "candy crush gameplay",
    "fruit ninja gameplay",
    "video game controller hands",
    "mobile gaming phone screen",
    "arcade game screen",
    "casual phone game play",
]

def fetch_gaming_clip(beat_num, clips_dir):
    """Search for safe gaming/gameplay footage as last-resort clip fallback."""
    query = random.choice(GAMING_QUERIES)
    print(f"  🎮 Gaming clip fallback: '{query}'")
    result = fetch_pexels_video(query, beat_num, clips_dir)
    if result:
        return result
    result = fetch_pixabay_video(query, beat_num, clips_dir)
    return result


# ============================================================
# PEXELS VIDEO CLIP
# ============================================================
def fetch_pexels_video(keywords, beat_num, clips_dir):
    try:
        page = random.randint(1, 3)
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": keywords, "per_page": 15, "orientation": "portrait", "page": page},
            timeout=30,
        )
        if resp.status_code == 200:
            videos = resp.json().get("videos", [])
            if videos:
                video     = random.choice(videos[:5])
                mp4_files = [f for f in video.get("video_files", []) if f.get("file_type") == "video/mp4"]
                if mp4_files:
                    mp4_files.sort(key=lambda x: abs(x.get("width", 0) - 720))
                    vid_resp = requests.get(mp4_files[0]["link"], timeout=60, stream=True)
                    if vid_resp.status_code == 200:
                        out = os.path.join(clips_dir, f"beat_{beat_num:02d}_pexels.mp4")
                        with open(out, "wb") as f:
                            for chunk in vid_resp.iter_content(8192):
                                f.write(chunk)
                        print(f"  ✅ Pexels video beat {beat_num}: {keywords}")
                        return out
        return None
    except Exception as e:
        print(f"  ❌ Pexels video error: {e}")
        return None


# ============================================================
# PIXABAY VIDEO CLIP
# ============================================================
def fetch_pixabay_video(keywords, beat_num, clips_dir):
    try:
        query = "+".join(keywords.split()[:4])
        resp  = requests.get(
            "https://pixabay.com/api/videos/",
            params={"key": PIXABAY_API_KEY, "q": query, "per_page": 10, "video_type": "film"},
            timeout=30,
        )
        if resp.status_code == 200:
            hits = resp.json().get("hits", [])
            if hits:
                video = random.choice(hits[:5])
                for quality in ["medium", "small", "large"]:
                    url = video.get("videos", {}).get(quality, {}).get("url")
                    if url:
                        vid_resp = requests.get(url, timeout=60, stream=True)
                        if vid_resp.status_code == 200:
                            out = os.path.join(clips_dir, f"beat_{beat_num:02d}_pixabay.mp4")
                            with open(out, "wb") as f:
                                for chunk in vid_resp.iter_content(8192):
                                    f.write(chunk)
                            print(f"  ✅ Pixabay video beat {beat_num}: {keywords}")
                            return out
        return None
    except Exception as e:
        print(f"  ❌ Pixabay video error: {e}")
        return None


# ============================================================
# PROMPT ENHANCER — enriches before sending to Leonardo
# Adds cinematic quality boosters + fixes vague/short prompts
# ============================================================
# Phrases that signal a vague/weak prompt — we inject extra detail
VAGUE_SIGNALS = [
    "a person", "someone", "a man", "a woman", "they ",
    "their phone", "their face", "their computer",
    "a mix of", "emotions", "showing", "looking at",
]

DETAIL_INJECTIONS = [
    "extreme close-up filling the frame, face half-submerged in deep black shadow, single cold directional light source from below, hollow sunken eyes fixed on something off-frame in dread, film noir chiaroscuro contrast, ",
    "low angle Dutch tilt shot looking up at the subject, dramatic harsh side lighting casting long shadow on wall, intense atmospheric tension, dark void background, visible texture on skin and clothing, ",
    "medium close-up with Dutch angle, cold blue-white key light from one side leaving the other in absolute darkness, high contrast deep shadows, cinematic tension, wet reflective surface underfoot, ",
    "over-shoulder perspective showing subject from behind, blurred city neon lights smearing through rain-streaked glass in background, wet reflective floor, oppressive moody atmosphere, shallow depth of field, ",
    "wide shot from across the room, subject small and alone against massive dark environment, single harsh overhead light creating a pool of cold illumination, everything else in shadow, isolating, desolate, ",
]

# Per-format cinematic suffix with extra detail for Leonardo
STYLE_QUALITY_SUFFIX = {
    "dark_luxury":    "dramatic chiaroscuro lighting, deep blacks and shadow, rich gold accent details in background, expensive materials, photorealistic, ultra-detailed, 8K resolution, dark luxury cinematic, vertical 9:16 aspect ratio, anamorphic lens flare, subtle film grain, shallow depth of field, bokeh background",
    "dark_horror":    "eerie cold atmospheric lighting from below, deep green-black shadows, thin wisps of fog, unsettling off-center composition, desaturated color grade except for one sickly pale element, photorealistic, ultra-detailed, 8K resolution, dark horror cinematic, vertical 9:16 aspect ratio, subtle film grain, shallow depth of field",
    "abstract_dark":  "dark digital art atmosphere, particle dust floating in beams of cold light, deep space color depth, layered depth with foreground and background separation, photorealistic render, ultra-detailed, 8K resolution, dark cinematic, vertical 9:16 aspect ratio, film grain, shallow depth of field",
    "dark_cinematic": "dramatic film noir lighting, high contrast black and deep shadow, photorealistic, ultra-detailed, 8K resolution, dark cinematic, vertical 9:16 aspect ratio, anamorphic lens, subtle film grain, shallow depth of field, bokeh background",
    "illustrated":    "detailed dark graphic novel illustration, dramatic ink-shadow composition, high contrast cell shading, ultra-detailed, dark cinematic, vertical 9:16 aspect ratio",
}

def enhance_prompt(prompt, style):
    """
    Enforce 60-word minimum and inject cinematic richness into any vague prompt.
    Returns a stronger, more visually precise prompt for Leonardo AI.
    """
    prompt = prompt.strip()

    # Word count check is PRIMARY — always inject if under 60 words or if vague signals detected
    word_count = len(prompt.split())
    is_vague   = word_count < 60 or any(v in prompt.lower() for v in VAGUE_SIGNALS)

    if is_vague:
        injection = random.choice(DETAIL_INJECTIONS)
        prompt    = injection + prompt

    # Append quality suffix — skip only if prompt already has the full technical tag set
    has_full_tags = "8K" in prompt and "anamorphic" in prompt.lower() and "film grain" in prompt.lower()
    if not has_full_tags:
        suffix = STYLE_QUALITY_SUFFIX.get(style, STYLE_QUALITY_SUFFIX["dark_cinematic"])
        prompt = f"{prompt}, {suffix}"

    return prompt


# ============================================================
# GENERATE SINGLE IMAGE (Leonardo → Pexels → Pixabay)
# ============================================================
def generate_image(prompt, style, index, output_dir):
    enhanced = enhance_prompt(prompt, style)
    print(f"\n🎨 Image {index}: {enhanced[:80]}...")
    result = generate_leonardo(enhanced, style, index, output_dir)
    if result:
        return result
    # Pexels/Pixabay fallback: use original short prompt for keyword search
    result = get_pexels_fallback(prompt, index, output_dir)
    if result:
        return result
    result = get_pixabay_fallback(prompt, index, output_dir)
    if result:
        return result
    print(f"  ❌ All image sources failed for beat {index}")
    return None


# ============================================================
# GENERATE ALL VISUALS — BEAT-LOCKED (visual_type from beat field)
# ============================================================
def generate_all_images(script_data, output_dir="images", clips_dir="clips"):
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(clips_dir,  exist_ok=True)

    # Clear old files
    for d, exts in [(output_dir, (".jpg", ".png", ".mp4")), (clips_dir, (".mp4",))]:
        for f in os.listdir(d):
            if f.endswith(exts):
                os.remove(os.path.join(d, f))

    beats      = script_data.get("beats") or script_data.get("image_prompts", [])
    format_key = script_data.get("format", "story_lesson")
    vis_style  = FORMATS_VISUAL.get(format_key, "dark_cinematic")

    style_map = {
        "dark cinematic": "dark_cinematic",
        "dark luxury":    "dark_luxury",
        "horror":         "dark_horror",
        "abstract":       "abstract_dark",
        "illustrated":    "illustrated",
    }

    print(f"\n🎨 Generating visuals for {len(beats)} beats  |  Style: {vis_style}")
    print(f"🔑 Leonardo AI: DISABLED — clips only (Pexels/Pixabay video)")

    generated_visuals = []

    # Reset per-run keyword tracking
    _used_keywords.clear()

    STOCK_BLOCKLIST = {
        "psychological", "psychology", "abstract", "invisible", "concept",
        "emotion", "emotions", "metaphor", "symbolic", "theory", "mental",
        "cognitive", "subconscious", "aversion", "bias", "bubble", "fomo",
        "algorithm", "influence", "manipulation", "trick", "anchoring",
        "persuasion", "heuristic", "effect", "principle", "technique",
    }

    # Well-known proper nouns stock libraries have NO footage of
    PERSON_NAME_BLOCKLIST = {
        "elon", "musk", "zuckerberg", "mark", "buffett", "warren", "bezos",
        "gates", "bill", "jobs", "steve", "cialdini", "robert", "freud",
        "trump", "obama", "biden", "powell", "munger", "dalio", "ray",
        "soros", "george", "tesla", "facebook", "meta", "google", "apple",
        "amazon", "microsoft", "twitter", "tiktok", "instagram", "youtube",
    }

    def _sanitize_keywords(kws):
        """Strip abstract words and proper names that Pexels can't search for."""
        if not kws:
            return kws
        words = kws.split()
        filtered = []
        for w in words:
            wl = w.lower().rstrip("s,.")
            if wl in STOCK_BLOCKLIST:
                continue
            if wl in PERSON_NAME_BLOCKLIST:
                continue
            # Skip likely proper nouns (capitalized, >2 chars, not the first word)
            if filtered and w[0].isupper() and len(w) > 2 and not w.isupper():
                continue
            filtered.append(w)
        return " ".join(filtered) if filtered else kws

    for i, beat_data in enumerate(beats):
        beat_num      = beat_data.get("beat", i + 1)
        image_prompt  = beat_data.get("image_prompt") or beat_data.get("prompt", "")
        video_kws     = beat_data.get("video_keywords", "")
        style         = style_map.get(beat_data.get("style", ""), vis_style)

        # Strip abstract/psychology words and proper names that stock libraries don't carry
        if video_kws:
            clean_kws = _sanitize_keywords(video_kws)
            if clean_kws.strip():
                if clean_kws != video_kws:
                    print(f"  🔍 Keywords sanitized: '{video_kws}' → '{clean_kws}'")
                video_kws = clean_kws

        # If keywords were fully wiped by sanitization, extract from beat text
        if not video_kws.strip():
            beat_text = beat_data.get("text", "")
            # Take first 4 content words from beat text as fallback keywords
            stop = {"the","a","an","of","in","to","is","are","was","were","i","you",
                    "we","they","it","this","that","and","or","but","he","she","his","her"}
            kw_words = [w.strip(".,!?\"'") for w in beat_text.split()
                        if w.lower().strip(".,!?\"'") not in stop and len(w) > 2][:4]
            video_kws = " ".join(kw_words) if kw_words else "dark night cinematic"
            print(f"  🔍 Keywords rebuilt from text: '{video_kws}'")

        # Deduplicate video keywords — vary them so each beat searches differently
        if video_kws:
            original_kws = video_kws
            variation_idx = 0
            while video_kws in _used_keywords and variation_idx < len(_KW_VARIATIONS):
                video_kws = f"{original_kws} {_KW_VARIATIONS[variation_idx]}"
                variation_idx += 1
            _used_keywords.add(video_kws)

        # ALL beats use clips — Leonardo AI is disabled
        visual_type  = beat_data.get("visual_type", "clip")
        is_clip_beat = True   # always clip regardless of visual_type field

        print(f"\n🎬 Beat {beat_num}: VIDEO CLIP — {(video_kws or image_prompt)[:50]}")

        result      = None
        result_type = None

        if video_kws:
            result = fetch_pexels_video(video_kws, beat_num, clips_dir)
            if result:
                result_type = "clip"
            if not result:
                result = fetch_pixabay_video(video_kws, beat_num, clips_dir)
                if result:
                    result_type = "clip"

        # Last resort chain: gaming clip → stock photo (darkened)
        if not result:
            print(f"  ⚠️  No topic clip — trying gaming footage for beat {beat_num}")
            result = fetch_gaming_clip(beat_num, clips_dir)
            if result:
                result_type = "clip"

        if not result:
            print(f"  ⚠️  No clip at all — falling back to stock photo for beat {beat_num}")
            img = get_pexels_fallback(image_prompt, beat_num, output_dir)
            if not img:
                img = get_pixabay_fallback(image_prompt, beat_num, output_dir)
            if img:
                result      = img
                result_type = "image"

        if result and result_type:
            generated_visuals.append({
                "path":  result,
                "type":  result_type,
                "beat":  beat_num,
            })
        else:
            print(f"  ❌ All sources failed for beat {beat_num}")

        time.sleep(0.8)

    clips_n  = sum(1 for v in generated_visuals if v["type"] == "clip")
    images_n = sum(1 for v in generated_visuals if v["type"] == "image")
    print(f"\n✅ {len(generated_visuals)} visuals ready  ({images_n} images, {clips_n} clips)")
    return generated_visuals


# ============================================================
# TEST
# ============================================================
if __name__ == "__main__":
    print("🔑 Checking Leonardo AI keys...")
    for i, key in enumerate(LEONARDO_KEYS):
        t = check_leonardo_tokens(key)
        print(f"  Key {i+1}: {t} tokens")

    test_script = {
        "format": "story_lesson",
        "beats": [
            {
                "beat": 1, "timestamp": "0-4s",
                "text": "He lost everything in one hour",
                "image_prompt": "man staring at crashing stock screens, dark office, horror on face",
                "video_keywords": "stock market crash panic",
                "visual_type": "clip",
                "pace": "fast",
                "camera_motion": "zoom_in",
                "style": "dark cinematic",
            },
            {
                "beat": 2, "timestamp": "4-14s",
                "text": "Let me take you back to the beginning",
                "image_prompt": "young entrepreneur in dark empty office, single lamp, late night city skyline",
                "video_keywords": "dark office night lonely",
                "visual_type": "image",
                "pace": "medium",
                "camera_motion": "zoom_out",
                "style": "dark luxury",
            },
        ],
    }
    result = generate_all_images(test_script)
    if result:
        for v in result:
            print(f"  {v['type']:5s} beat {v['beat']}: {v['path']}")

"""
Dark Mind — Voiceover Generator
ElevenLabs TTS with voice pools per format.
Picks a random voice from the pool each run to avoid listener fatigue.
"""
import os
import sys
import json
import time
import random
import requests
from pathlib import Path
from dotenv import load_dotenv

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

# ============================================================
# KEY POOL — up to 3 ElevenLabs accounts, auto-rotate on quota
# ============================================================
_ALL_KEYS = [
    os.getenv("ELEVENLABS_API_KEY"),
    os.getenv("ELEVENLABS_API_KEY_2"),
    os.getenv("ELEVENLABS_API_KEY_3"),
]
ELEVENLABS_KEYS = [k for k in _ALL_KEYS if k]


def check_elevenlabs_credits(api_key):
    """Returns remaining character credits for this key, or -1 on error."""
    try:
        r = requests.get(
            "https://api.elevenlabs.io/v1/user/subscription",
            headers={"xi-api-key": api_key},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            used  = data.get("character_count", 0)
            limit = data.get("character_limit", 10000)
            return max(0, limit - used)
        return -1
    except Exception:
        return -1


def pick_best_key():
    """
    Returns (api_key, credits) for the key with the most credits remaining.
    Falls back to first key if credit check fails on all.
    """
    best_key     = ELEVENLABS_KEYS[0] if ELEVENLABS_KEYS else None
    best_credits = -1

    for key in ELEVENLABS_KEYS:
        credits = check_elevenlabs_credits(key)
        key_idx = ELEVENLABS_KEYS.index(key) + 1
        print(f"   ElevenLabs key {key_idx}: {credits} credits")
        if credits > best_credits:
            best_credits = credits
            best_key     = key

    return best_key, best_credits

# ============================================================
# VOICE POOLS — 3 voices per style, random pick each run
# All are free-tier ElevenLabs voices
# ============================================================
VOICE_POOLS = {
    "deep_male": [
        {"id": "knrPHWnBmmDHMoiMeP3l", "name": "Liam",    "stability": 0.4,  "style": 0.45},
        {"id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh",    "stability": 0.38, "style": 0.5},
        {"id": "ErXwobaYiN019PkySvjV", "name": "Antoni",  "stability": 0.42, "style": 0.4},
    ],
    "whispery_male": [
        {"id": "N2lVS1w4EtoT3dr4eOWO", "name": "Callum",  "stability": 0.5,  "style": 0.3},
        {"id": "SOYHLrjzK2X1ezoPC6cr", "name": "Harry",   "stability": 0.48, "style": 0.28},
        {"id": "yoZ06aMxZJJ28mfd3POQ", "name": "Sam",     "stability": 0.52, "style": 0.32},
    ],
    "calm_female": [
        {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella",   "stability": 0.45, "style": 0.4},
        {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel",  "stability": 0.5,  "style": 0.35},
        {"id": "MF3mGyEYCl7XYWbV9V6O", "name": "Emily",   "stability": 0.47, "style": 0.38},
    ],
    "energetic_male": [
        {"id": "nPczCjzI2devNBz1zQrb", "name": "Brian",   "stability": 0.3,  "style": 0.55},
    ],
}

# Shared settings applied to all voices
SHARED_SETTINGS = {
    "similarity_boost":  0.8,
    "use_speaker_boost": True,
    "speed":             0.95,
}

# Format → voice pool fallback
FORMAT_VOICE_DEFAULTS = {
    "story_lesson":      "deep_male",
    "scary_truth":       "whispery_male",
    "hidden_psychology": "calm_female",
}

DEFAULT_VOICE_TYPE = "deep_male"

_VOICE_HISTORY_FILE = Path(__file__).parent / "voice_history.json"


def _load_voice_history():
    try:
        if _VOICE_HISTORY_FILE.exists():
            return json.loads(_VOICE_HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_voice_history(history):
    try:
        _VOICE_HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")
    except Exception:
        pass


# ============================================================
# PICK VOICE FROM POOL — never repeat the same voice twice in a row
# ============================================================
def pick_voice(voice_type):
    pool = VOICE_POOLS.get(voice_type, VOICE_POOLS[DEFAULT_VOICE_TYPE])
    if len(pool) == 1:
        return pool[0]

    history    = _load_voice_history()
    last_used  = history.get(voice_type, "")

    # Exclude the last used voice so we always rotate
    available  = [v for v in pool if v["name"] != last_used]
    if not available:
        available = pool   # safety: all voices exhausted, allow repeats

    voice = random.choice(available)

    history[voice_type] = voice["name"]
    _save_voice_history(history)
    return voice


# ============================================================
# GENERATE VOICEOVER
# ============================================================
def generate_voiceover(script_data, output_path=None):
    script = script_data.get("script", "").strip()
    if not script:
        print("❌ No script text found")
        return None

    # Resolve voice type
    voice_type = script_data.get("voice_type")
    if not voice_type or voice_type not in VOICE_POOLS:
        fmt        = script_data.get("format", "")
        voice_type = FORMAT_VOICE_DEFAULTS.get(fmt, DEFAULT_VOICE_TYPE)

    voice = pick_voice(voice_type)

    if output_path is None:
        os.makedirs("audio", exist_ok=True)
        output_path = f"audio/voiceover_{int(time.time())}.mp3"
    else:
        parent = os.path.dirname(output_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    word_count = len(script.split())
    print(f"\n🎙️ Generating voiceover...")
    print(f"   Voice type : {voice_type}")
    print(f"   Voice name : {voice['name']}  (randomly picked from pool)")
    print(f"   Words      : {word_count}")
    print(f"   Output     : {output_path}")
    print(f"   Checking {len(ELEVENLABS_KEYS)} ElevenLabs key(s)...")

    # Pick the key with most credits
    api_key, credits = pick_best_key()
    if not api_key:
        print("❌ No ElevenLabs API key found")
        return None
    print(f"   Using key with {credits} credits remaining")

    url     = f"https://api.elevenlabs.io/v1/text-to-speech/{voice['id']}"
    payload = {
        "text":     script,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability":         voice["stability"],
            "similarity_boost":  SHARED_SETTINGS["similarity_boost"],
            "style":             voice["style"],
            "use_speaker_boost": SHARED_SETTINGS["use_speaker_boost"],
        },
    }

    # Try each key in order — rotate on quota_exceeded
    keys_to_try = [api_key] + [k for k in ELEVENLABS_KEYS if k != api_key]

    for key_idx, current_key in enumerate(keys_to_try):
        headers = {"xi-api-key": current_key, "Content-Type": "application/json"}

        for attempt in range(3):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=120)

                if response.status_code == 200:
                    with open(output_path, "wb") as f:
                        f.write(response.content)
                    size_kb = os.path.getsize(output_path) / 1024
                    print(f"✅ Voiceover saved — {size_kb:.0f} KB  (key {key_idx + 1})")
                    return output_path

                # Quota exceeded → try next key immediately
                if response.status_code == 401:
                    try:
                        detail = response.json().get("detail", {})
                        if isinstance(detail, dict) and detail.get("status") == "quota_exceeded":
                            print(f"   ⚠️  Key {key_idx + 1} quota exceeded — rotating...")
                            break   # break inner loop → next key
                    except Exception:
                        pass

                print(f"❌ ElevenLabs error {response.status_code}: {response.text[:300]}")
                return None

            except requests.exceptions.ConnectionError as e:
                wait = 5 * (attempt + 1)
                print(f"   ⚠️  Connection error (attempt {attempt+1}/3): {e.__class__.__name__} — retrying in {wait}s...")
                time.sleep(wait)
            except Exception as e:
                print(f"❌ Voiceover exception: {e}")
                return None

    print("❌ All ElevenLabs keys exhausted or failed")
    return None


# ============================================================
# TEST
# ============================================================
if __name__ == "__main__":
    test_script = {
        "format": "story_lesson",
        "voice_type": "deep_male",
        "script": (
            "On January 20th 2011 Richard Branson watched his private island burn. "
            "Eighty million dollars. Gone. In four minutes. "
            "But here is what nobody tells you. The next morning he woke up at five. "
            "Exercised. Read. Planned his day. Because your habits are not for when things are good. "
            "They are for when everything falls apart. "
            "Go back to the very first second. Watch his hands. Now you understand why."
        ),
    }
    # Test multiple runs to verify different voices are picked
    for i in range(3):
        voice = pick_voice("deep_male")
        print(f"Run {i+1}: would use {voice['name']}")

    result = generate_voiceover(test_script, "audio/test_voiceover.mp3")
    if result:
        print(f"\n🎉 Done: {result}")

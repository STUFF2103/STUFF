"""
Dark Mind — Groq Key Pool
Auto-rotates across up to 3 Groq API keys on 429 rate-limit errors.
Same pattern as ElevenLabs key rotation.
"""
import os
import time
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_ALL_KEYS = [
    os.getenv("GROQ_API_KEY"),
    os.getenv("GROQ_API_KEY_2"),
    os.getenv("GROQ_API_KEY_3"),
]
GROQ_KEYS = [k for k in _ALL_KEYS if k and k.strip()]

# Track when each key was rate-limited {key: exhausted_at_timestamp}
_exhausted: dict = {}

# How long to wait before retrying an exhausted key (Groq TPD resets at midnight UTC)
# We use 25 minutes — slightly more than the "try again in 24m" message
_COOLDOWN_SECS = 25 * 60


def _available_keys():
    now = time.time()
    available = []
    for k in GROQ_KEYS:
        exhausted_at = _exhausted.get(k)
        if exhausted_at is None or (now - exhausted_at) > _COOLDOWN_SECS:
            available.append(k)
    return available


def get_completion(messages, model="llama-3.3-70b-versatile",
                   temperature=0.85, max_tokens=4096):
    """
    Call Groq with automatic key rotation on 429.
    Tries all available keys before giving up.
    Returns the message content string, or raises the last exception.
    """
    keys_to_try = _available_keys()
    if not keys_to_try:
        # All keys exhausted — wait for the soonest cooldown to expire
        soonest = min(_exhausted.values())
        wait = max(0, _COOLDOWN_SECS - (time.time() - soonest))
        print(f"   ⚠️  All Groq keys exhausted — waiting {wait:.0f}s for reset...")
        time.sleep(wait + 5)
        keys_to_try = GROQ_KEYS   # retry all after wait

    last_exc = None
    for key in keys_to_try:
        idx = GROQ_KEYS.index(key) + 1
        try:
            client = Groq(api_key=key)
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()

        except Exception as e:
            err_str = str(e)
            if "rate_limit_exceeded" in err_str or "429" in err_str:
                print(f"   ⚠️  Groq key {idx} rate-limited — rotating to next key...")
                _exhausted[key] = time.time()
                last_exc = e
                continue
            # Non-rate-limit error — raise immediately
            raise

    raise last_exc or RuntimeError("All Groq keys failed")


def status():
    now = time.time()
    lines = []
    for i, k in enumerate(GROQ_KEYS, 1):
        ex = _exhausted.get(k)
        if ex and (now - ex) < _COOLDOWN_SECS:
            remaining = int(_COOLDOWN_SECS - (now - ex))
            lines.append(f"  Key {i}: EXHAUSTED (resets in {remaining//60}m{remaining%60:02d}s)")
        else:
            lines.append(f"  Key {i}: available")
    return "\n".join(lines)


if __name__ == "__main__":
    print(f"Groq keys loaded: {len(GROQ_KEYS)}")
    print(status())

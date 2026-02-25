"""
Dark Mind — Script Writer
Groq (llama-3.3-70b-versatile) → script + beats with full visual/pacing schema.
New in this version:
  - 7-field beats schema (visual_type, pace, camera_motion added)
  - Top-level hook_text field (ALL CAPS, ≤8 words)
  - 3-attempt retry: checks word count ≥ 150, reinjects feedback
  - No Spanish translation call (kept as utility, not called)
  - Sharper prompt language (physical reactions, specific details)
"""
import os
import sys
import json
import random
from dotenv import load_dotenv

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()
from groq_pool import get_completion as _groq_call

# ============================================================
# 3 POWER FORMATS
# ============================================================
FORMATS = {
    "story_lesson": {
        "name": "Story Lesson",
        "rpm": "high",
        "length": (70, 100),
        "voice": "deep_male",
        "music": "cinematic",
        "visual": "dark_luxury",
        "topics": [
            "billionaire who lost everything and came back",
            "trader who discovered a psychological pattern",
            "entrepreneur who failed 5 times before succeeding",
            "investor who predicted a market crash",
            "CEO who was fired and built a bigger company",
            "hedge fund manager who outsmarted Wall Street",
            "crypto whale who went broke and rebuilt",
        ],
    },
    "scary_truth": {
        "name": "Scary Truth",
        "rpm": "high",
        "length": (60, 90),
        "voice": "whispery_male",
        "music": "tense",
        "visual": "dark_horror",
        "topics": [
            "building that predicted its own destruction",
            "person who disappeared and was found years later",
            "historical event that was covered up",
            "conspiracy that turned out to be true",
            "place that appears and disappears on maps",
            "government experiment that went wrong",
            "technology that was suppressed for decades",
        ],
    },
    "hidden_psychology": {
        "name": "Hidden Psychology",
        "rpm": "medium",
        "length": (60, 80),
        "voice": "calm_female",
        "music": "dark_ambient",
        "visual": "abstract_dark",
        "topics": [
            "manipulation signs in relationships",
            "psychological tricks used on you daily",
            "why smart people stay poor",
            "signs someone secretly resents you",
            "dark side of social media on your brain",
            "how your childhood trauma runs your adult life",
            "psychological reason you self-sabotage",
        ],
    },
}

# ============================================================
# BEAT SCHEMA DOCUMENTATION (embedded in prompt)
# ============================================================
BEAT_SCHEMA_EXAMPLE = """{
  "beat": 1,
  "timestamp": "0-4s",
  "text": "I watched $420,000 disappear in four minutes",
  "image_prompt": "extreme close-up of a 38-year-old male trader's face filling the frame, skin ashen and clammy, jaw locked tight, veins visible at the temple, eyes red-rimmed and hollow fixed on something off-screen in pure dread, single tear track dried on left cheek, rumpled white dress shirt collar open, tie pulled loose, cold electric blue monitor glow illuminating only the left half of his face leaving the right in deep black shadow, reflection of cascading red numbers visible in his wide pupils, pitch black background behind him, shallow depth of field blurring into darkness, film noir chiaroscuro contrast, photorealistic, ultra-detailed, 8K, dark cinematic, vertical 9:16, subtle film grain",
  "video_keywords": "stock market crash trader panic",
  "visual_type": "clip",
  "pace": "fast",
  "camera_motion": "zoom_in",
  "style": "dark cinematic"
}"""

BEAT_RULES = """BEAT FIELDS:
- visual_type: "image" (emotional/slow/symbolic) | "clip" (action/movement/real events)
- pace: "fast"=2-4s | "medium"=5-8s | "slow"=8-12s
- camera_motion: "zoom_in" | "zoom_out" | "pan_right" | "pan_left" | "shake"
- hook_text: ALL CAPS, max 8 words, most shocking fact in the whole story

IMAGE PROMPT — MINIMUM 60 WORDS, ALL 8 LAYERS REQUIRED:
① Subject: exact age + clothing (NEVER "a man" — say "38-year-old trader in sweat-soaked white shirt, tie loose")
② Body language: physical details only (NEVER "looking scared" — say "jaw locked, knuckles bone-white, shoulders caved inward")
③ Setting: specific location + 2 physical details (NEVER "an office" — say "empty trading floor 3am, 40 dark monitors")
④ Lighting: direction + color temp ("cold electric-blue monitor glow from below" / "single amber desk lamp")
⑤ Camera: angle + framing ("extreme close-up filling frame" / "low Dutch-angle tilt" / "over-shoulder shot")
⑥ Color palette: 2-3 dominant colors ("deep black, blood red, sickly green")
⑦ Atmosphere: 1 environmental detail ("cigarette smoke curling in monitor glow" / "rain streaking the window")
⑧ End EVERY prompt with: "photorealistic, ultra-detailed, 8K, dark cinematic, vertical 9:16, anamorphic lens, film grain, shallow depth of field"

UNIQUENESS: Every beat MUST show a DIFFERENT scene. Different location, different angle, different subject framing. No two beats can look alike.

VIDEO KEYWORDS — CRITICAL RULES:
✅ GOOD: "stock market red numbers screen", "cash hands counting table", "city aerial night", "courtroom judge gavel", "man crying car dark", "phone screen scrolling ads"
❌ BAD — person names (Pexels has NO footage of named people): "elon musk", "mark zuckerberg", "robert cialdini", "warren buffett"
❌ BAD — abstract concepts with no visual: "anchoring effect", "psychological bias", "manipulation", "algorithm", "influence"
❌ BAD — company names: "facebook headquarters", "tesla factory", "google office"
RULE: Describe only what the CAMERA PHYSICALLY SEES — the action, the object, the environment. Never who or what concept. 3-4 words maximum.
"""


# ============================================================
# STRUCTURE PER FORMAT
# ============================================================
def get_structure(format_key):
    if format_key == "story_lesson":
        return """
STRUCTURE (follow exactly):
1. HOOK (0-5s): Most shocking moment of the story FIRST. No context. Drop them into the action.
2. REWIND (5-15s): "But let's go back to the beginning..." Build context fast.
3. THE STORY (15-70s): Full real story. Specific details. Real emotions. Tension builds relentlessly.
4. THE LESSON (70-100s): Extract the psychology/finance/business insight. Make it feel like a secret being revealed.
5. THE PUNCHLINE (100-110s): One powerful line they'll screenshot and share.
6. REWATCH TRIGGER (110-120s): "Go back to [specific timestamp]. You missed something important."
If story continues: "Part 2 drops tomorrow. Follow so you don't miss what happens next."
"""
    elif format_key == "scary_truth":
        return """
STRUCTURE (follow exactly):
1. HOOK (0-5s): Most terrifying/shocking detail first. No context. Pure impact.
2. SETUP (5-20s): "Here's what most people don't know..." Establish the mystery.
3. THE EVIDENCE (20-60s): Real facts, dates, locations. Specific. Credible. Building dread.
4. THE TWIST (60-80s): The detail that changes everything.
5. CLIFFHANGER (80-90s): Leave one question unanswered. "Part 2 reveals what really happened."
"""
    else:
        return """
STRUCTURE (follow exactly):
1. HOOK (0-3s): Statement that sounds impossible but is true. No context.
2. PROOF (3-20s): Three real facts that prove it. Fast. Punchy.
3. THE DEEP TRUTH (20-45s): Why this happens. The psychology behind it.
4. PERSONAL HIT (45-55s): Make it personal. "You've already experienced this."
5. REWATCH TRIGGER (55-60s): "Read the first line again. Now it hits different."
"""


# ============================================================
# SCRIPT WRITER — with 3-attempt retry
# ============================================================
def write_script(topic, format_key, trend_data=None,
                 is_part2=False, part1_summary=None,
                 used_topics=None, used_hooks=None):
    fmt = FORMATS[format_key]
    min_len, max_len = fmt["length"]

    trend_ctx  = f"\nTRENDING RIGHT NOW: {trend_data}" if trend_data else ""
    part2_ctx  = ""
    if is_part2 and part1_summary:
        part2_ctx = (
            f"\nThis is PART 2. Part 1 summary: {part1_summary}\n"
            "Start by briefly recapping Part 1 in one sentence, then continue the story."
        )

    # Build blacklist context — tell the model exactly what NOT to repeat
    blacklist_ctx = ""
    if used_topics:
        topics_list = "\n".join(f"  - {t}" for t in used_topics[:10])
        blacklist_ctx += f"\nTOPICS ALREADY MADE (DO NOT repeat or closely resemble any of these):\n{topics_list}\n"
    if used_hooks:
        hooks_list = "\n".join(f"  - {h}" for h in used_hooks[:15])
        blacklist_ctx += (
            f"\nHOOKS ALREADY USED (your hook_text MUST be completely different in structure, "
            f"wording, and emotional angle from ALL of these):\n{hooks_list}\n"
            f"Pick a different hook TYPE: question / dark statistic / identity attack / "
            f"confession / historical fact / shocking contrast — NOT a loss story opener unless "
            f"it uses completely different framing.\n"
        )

    base_prompt = f"""You are writing a script for a viral faceless YouTube Shorts and TikTok channel.

FORMAT: {fmt['name']}
TOPIC: {topic}
TARGET LENGTH: {min_len}-{max_len} seconds. Write 250-280 words — full story, every word earns its place.
{trend_ctx}{part2_ctx}{blacklist_ctx}

{get_structure(format_key)}

WRITING RULES:
- ABSOLUTE RULE: NEVER start with "Imagine", "Picture this", "Have you ever", "What if", or any hypothetical. The very first word must open a REAL event. Like: "In 2009, a Goldman Sachs trader..." or "He had $2.3 million at 9am." or "The call came at 3am."
- ABSOLUTE RULE: Tell ONE specific story about ONE specific real person. Not "billionaires in general" or "studies show". ONE person, ONE event, ONE day. Give them a name, an age, a dollar amount.
- Write like you're whispering a secret to someone at 2am who can't leave
- Every sentence must create a physical reaction — stomach drop, heart race, jaw clench
- Use specific dollar amounts, exact dates, real names — vagueness kills virality
- Gen Z language — raw, direct, no corporate speak
- Short sentences. Hit hard. Move fast. No filler words.
- English only

{BEAT_RULES}

REFERENCE BEAT EXAMPLE — every beat you write must follow this exact structure:
{BEAT_SCHEMA_EXAMPLE}

Divide the script into 8-14 beats. STRICT REQUIREMENTS:
1. Every beat needs ALL 8 fields: text, image_prompt, video_keywords, visual_type, pace, camera_motion, style, plus beat number and timestamp
2. Every image_prompt MINIMUM 60 WORDS containing all 8 cinematic layers
3. Every beat shows a COMPLETELY DIFFERENT scene — different location, different angle, different subject framing from every other beat
4. Every beat's video_keywords MUST be unique — zero duplicates across all beats (e.g. if beat 1 uses "stock market crash trader panic" no other beat can use those same words)

Return ONLY valid JSON (absolutely no markdown, no code fences, no extra text — start with {{ and end with }}):
{{
    "format": "{format_key}",
    "topic": "{topic}",
    "hook_line": "the very first spoken line",
    "hook_text": "ALL CAPS MAX 8 WORDS MOST SHOCKING THING",
    "script": "full script 250-280 words, full story",
    "rewatch_trigger": "the final rewatch instruction line",
    "is_serialized": false,
    "part2_teaser": "",
    "beats": [your 8-14 beat objects here, each following the REFERENCE BEAT EXAMPLE structure above],
    "suggested_music": "one of: cinematic tense dark_ambient phonk lofi",
    "voice_type": "{fmt['voice']}",
    "estimated_duration": 90
}}"""

    last_word_count = 0
    for attempt in range(3):
        retry_injection = ""
        if attempt > 0:
            retry_injection = (
                f"\n\n--- RETRY INSTRUCTION ---\n"
                f"Your last attempt had only {last_word_count} words in the script field. "
                f"That is NOT enough. You need 250-280 words minimum. "
                f"Add MORE story depth, specific details, real emotions, exact dollar amounts, names, and tension. "
                f"Every sentence should make the reader feel something physical. Do not summarize — tell the FULL story.\n"
            )

        prompt = base_prompt + retry_injection

        try:
            # Increase temperature on retries to force more variety
            temp = 0.85 + (attempt * 0.08)
            content = _groq_call(
                messages=[{"role": "user", "content": prompt}],
                temperature=min(temp, 1.0),
                max_tokens=4096,
            )

            if not content:
                print(f"   ⚠️  Attempt {attempt+1}: empty response from model")
                continue

            # Strip markdown code fences if present
            if "```" in content:
                parts = content.split("```")
                for p in parts:
                    p = p.strip()
                    if p.startswith("json"):
                        p = p[4:].strip()
                    if p.startswith("{"):
                        content = p
                        break

            # Find JSON object boundaries if there's surrounding text
            if not content.startswith("{"):
                start = content.find("{")
                if start != -1:
                    content = content[start:]

            # Find last closing brace to trim any trailing text
            last_brace = content.rfind("}")
            if last_brace != -1:
                content = content[:last_brace + 1]

            data = json.loads(content.strip())

            # Validate word count
            word_count = len(data.get("script", "").split())
            last_word_count = word_count

            if word_count >= 230:
                print(f"   ✅ Script OK: {word_count} words (attempt {attempt+1})")
                return data

            print(f"   ⚠️  Attempt {attempt+1}: only {word_count} words — retrying...")

        except json.JSONDecodeError as e:
            print(f"   ⚠️  Attempt {attempt+1}: JSON parse error: {e}")
        except Exception as e:
            print(f"   ❌ Attempt {attempt+1}: {e}")
            return None

    # Return last result even if short (better than nothing)
    print(f"   ⚠️  Returning script after 3 attempts ({last_word_count} words)")
    try:
        return data
    except NameError:
        return None


# ============================================================
# FORMAT INFERENCE — pick best format for a given idea
# ============================================================
def infer_format(idea):
    """Pick the most fitting format based on topic keywords."""
    idea_lower = idea.lower()
    if any(w in idea_lower for w in [
        "trader", "market", "invest", "bitcoin", "stock", "billionaire",
        "money", "broke", "million", "failed", "startup", "bankrupt",
        "hedge", "crypto", "wealth", "entrepreneur", "ceo", "fired",
    ]):
        return "story_lesson"
    if any(w in idea_lower for w in [
        "disappear", "mystery", "cover", "secret", "conspiracy",
        "ghost", "haunted", "killed", "dark truth", "government",
        "suppressed", "experiment", "evidence", "cover-up", "missing",
    ]):
        return "scary_truth"
    if any(w in idea_lower for w in [
        "psychology", "manipulat", "narciss", "toxic", "mental",
        "trauma", "brain", "mind", "self-sabotage", "pattern",
        "behavior", "childhood", "social media", "habit",
    ]):
        return "hidden_psychology"
    return random.choice(list(FORMATS.keys()))


# ============================================================
# TOPIC PICKER (trend-aware)
# ============================================================
def pick_topic_and_format(trend_data=None):
    format_key = random.choice(list(FORMATS.keys()))
    fmt        = FORMATS[format_key]

    if trend_data:
        try:
            content = _groq_call(
                messages=[{"role": "user", "content": (
                    f'Given this trending topic: "{trend_data}"\n'
                    f'Pick the most viral angle for a {fmt["name"]} format video.\n'
                    f'Return ONLY a JSON object: {{"topic": "...", "why": "..."}}'
                )}],
                temperature=0.9,
            )
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            result = json.loads(content.strip())
            return format_key, result["topic"]
        except Exception:
            pass

    return format_key, random.choice(fmt["topics"])


# ============================================================
# SPANISH TRANSLATION (utility — NOT called by default)
# ============================================================
def translate_to_spanish(script_data):
    """Translate script to Latin American Spanish. Call manually if needed."""
    try:
        content = _groq_call(
            messages=[{"role": "user", "content": (
                "Translate this video script to Latin American Spanish Gen Z.\n"
                "Keep the same energy. Keep names, numbers, dates original.\n\n"
                f"Script:\n{script_data['script']}\n\n"
                "Return ONLY: {\"script_spanish\": \"...\", \"hook_line_spanish\": \"...\"}"
            )}],
            temperature=0.7,
        )
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        return json.loads(content.strip())
    except Exception as e:
        print(f"Translation error: {e}")
        return None


# ============================================================
# MAIN ENTRY
# ============================================================
def generate_script(trend_data=None, manual_idea=None,
                    is_part2=False, part1_summary=None,
                    used_topics=None, used_hooks=None):
    print("\n✍️ Generating script...")

    if manual_idea:
        format_key = infer_format(manual_idea)
        topic      = manual_idea
        print(f"   Manual idea  : {topic}")
        print(f"   Format chosen: {FORMATS[format_key]['name']} (auto-inferred)")
    else:
        format_key, topic = pick_topic_and_format(trend_data)
        print(f"   Format : {FORMATS[format_key]['name']}")
        print(f"   Topic  : {topic}")

    script_data = write_script(
        topic, format_key, trend_data, is_part2, part1_summary,
        used_topics=used_topics, used_hooks=used_hooks,
    )

    if not script_data:
        print("❌ Script generation failed")
        return None

    beats      = script_data.get("beats", [])
    word_count = len(script_data.get("script", "").split())

    print(f"\n✅ SCRIPT GENERATED!")
    print(f"   Voice    : {script_data.get('voice_type')}")
    print(f"   Music    : {script_data.get('suggested_music')}")
    print(f"   Duration : ~{script_data.get('estimated_duration')}s")
    print(f"   Words    : {word_count}")
    print(f"   Beats    : {len(beats)}")
    print(f"   Hook     : {script_data.get('hook_text', 'N/A')}")

    # Show beat pacing summary
    paces = [b.get("pace", "?") for b in beats]
    types = [b.get("visual_type", "?") for b in beats]
    print(f"   Pacing   : {paces}")
    print(f"   Visuals  : {types}")

    print(f"\n🪝 HOOK LINE: {script_data.get('hook_line')}")
    print(f"\n📝 SCRIPT PREVIEW:")
    print("-" * 50)
    print(script_data.get("script", "")[:350] + "...")
    print("-" * 50)

    return script_data


# ============================================================
# TEST
# ============================================================
if __name__ == "__main__":
    result = generate_script(manual_idea="trader who lost $420k in 4 minutes")
    if result:
        print(f"\n🎬 Beats: {len(result.get('beats', []))}")
        for b in result.get("beats", [])[:3]:
            print(f"  Beat {b['beat']}: [{b.get('pace')}] [{b.get('visual_type')}] [{b.get('camera_motion')}]")
            print(f"    Text: {b.get('text', '')[:80]}")

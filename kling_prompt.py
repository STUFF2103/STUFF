import os
import random
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ============================================================
# VISUAL STYLES (rotating randomly)
# ============================================================
VISUAL_STYLES = [
    "handheld shaky phone camera footage, person filming from crowd, amateur style",
    "bodycam POV footage, first person perspective, running and moving through scene",
    "crowd POV watching from distance, zoom in shakily toward building",
    "close up zoomed in shaky cam, extreme detail of destruction and debris",
    "phone camera held at chest height, amateur witness footage style"
]

# ============================================================
# GENERATE KLING AI PROMPT
# ============================================================
def generate_kling_prompt(story, script_data):
    visual_style = random.choice(VISUAL_STYLES)
    emotional_angle = story.get("emotional_angle", "human_rescue")
    location = story.get("location", "urban city")
    building_type = story.get("building_type", "building")
    script = script_data.get("script", "")

    prompt = f"""You are a video prompt engineer for Kling AI video generator.

Create a detailed, vivid video generation prompt for this story:

STORY: {story.get('chosen_story')}
LOCATION: {location}
BUILDING TYPE: {building_type}
EMOTIONAL ANGLE: {emotional_angle}
SCRIPT HOOK: {script_data.get('hook_line', '')}
VISUAL STYLE: {visual_style}

Requirements:
- The prompt must describe EXACTLY what should be seen in the video
- Must feel like raw authentic footage, NOT professional filming
- Must visually match the emotional angle ({emotional_angle})
- Must show the building and the dramatic moment
- 9:16 vertical format for TikTok/Reels
- No text, no logos, no watermarks in the scene
- Photorealistic, gritty, authentic

Return ONLY a JSON object:
{{
    "main_prompt": "detailed video prompt here (50-80 words)",
    "negative_prompt": "what to avoid in the video",
    "visual_style": "{visual_style}",
    "key_moment": "the single most important visual moment to capture"
}}"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8
    )

    try:
        import json
        content = response.choices[0].message.content.strip()
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        result = json.loads(content.strip())
        return result
    except Exception as e:
        print(f"Prompt parse error: {e}")
        return None

# ============================================================
# DISPLAY PROMPT FOR KLING AI WEBSITE
# ============================================================
def display_kling_instructions(story, script_data):
    print("\n" + "="*60)
    print("🎬 KLING AI VIDEO GENERATION INSTRUCTIONS")
    print("="*60)

    prompt_data = generate_kling_prompt(story, script_data)

    if not prompt_data:
        print("❌ Failed to generate prompt")
        return None

    print(f"\n📋 COPY THIS PROMPT TO KLINGAI.COM:")
    print("-"*60)
    print(prompt_data.get("main_prompt"))
    print("-"*60)

    print(f"\n🚫 NEGATIVE PROMPT (paste in negative prompt field):")
    print("-"*60)
    print(prompt_data.get("negative_prompt"))
    print("-"*60)

    print(f"\n🎯 KEY MOMENT TO CAPTURE:")
    print(prompt_data.get("key_moment"))

    print(f"\n⚙️ KLING AI SETTINGS:")
    print("  • Model: Kling v1.6")
    print("  • Mode: Standard")
    print("  • Duration: 5 seconds")
    print("  • Aspect Ratio: 9:16 (vertical)")
    print("  • Creativity: 0.5")

    print(f"\n📥 AFTER GENERATING:")
    print("  1. Download the video from Kling AI")
    print("  2. Save it to your clips folder:")
    print(f"     C:\\Users\\mehdi\\lastsecondsbc\\clips\\")
    print("  3. Name it: clip_1.mp4")
    print("  4. Run: python assembler.py")

    print("\n" + "="*60)

    return prompt_data

# ============================================================
# TEST
# ============================================================
if __name__ == "__main__":
    test_story = {
        "chosen_story": "A condemned 1960s apartment building in Detroit was scheduled for demolition when workers discovered a dog trapped inside. The demolition countdown had already started when a worker heard barking from the 3rd floor.",
        "source": "AI Generated",
        "viral_score": 9,
        "emotional_angle": "animal_rescue",
        "location": "Detroit, USA",
        "building_type": "apartment building"
    }

    test_script = {
        "voice_style": "casual_energetic",
        "suggested_music_mood": "suspenseful",
        "script": "BOOM! Demolition day in Detroit! But how did we get here? Condemned 1960s apartment building, countdown started, then barking from 3rd floor! Workers rush in, seconds to spare, will they save the pup? Caught on bodycam, you won't believe... Inspired by real events! Did they make it out?!",
        "hook_line": "BOOM! Demolition day in Detroit!",
        "rewatch_trigger": "Did they make it out?!",
        "suggested_music_mood": "suspenseful"
    }

    display_kling_instructions(test_story, test_script)

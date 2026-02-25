import os
import requests
import json
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ============================================================
# GOOGLE NEWS SCRAPER
# ============================================================
def get_google_news():
    try:
        keywords = [
            "building demolition",
            "building collapse",
            "abandoned building",
            "dangerous construction",
            "controlled demolition"
        ]
        stories = []
        for keyword in keywords:
            url = f"https://news.google.com/rss/search?q={keyword.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                for item in root.findall(".//item")[:3]:
                    title = item.find("title")
                    description = item.find("description")
                    stories.append({
                        "title": title.text if title is not None else "",
                        "text": description.text[:500] if description is not None else "",
                        "score": 100,
                        "source": "Google News"
                    })
        return stories
    except Exception as e:
        print(f"Google News error: {e}")
        return []

# ============================================================
# BING NEWS SCRAPER
# ============================================================
def get_bing_news():
    try:
        keywords = [
            "building demolition",
            "building collapse",
            "construction accident",
            "abandoned building rescue"
        ]
        stories = []
        for keyword in keywords:
            url = f"https://www.bing.com/news/search?q={keyword.replace(' ', '+')}&format=rss"
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                for item in root.findall(".//item")[:3]:
                    title = item.find("title")
                    description = item.find("description")
                    stories.append({
                        "title": title.text if title is not None else "",
                        "text": description.text[:500] if description is not None else "",
                        "score": 90,
                        "source": "Bing News"
                    })
        return stories
    except Exception as e:
        print(f"Bing News error: {e}")
        return []

# ============================================================
# YOUTUBE TRENDING SCRAPER
# ============================================================
def get_youtube_trending():
    try:
        keywords = [
            "building demolition bodycam",
            "building collapse caught on camera",
            "abandoned building exploration"
        ]
        stories = []
        for keyword in keywords:
            url = f"https://www.youtube.com/feeds/videos.xml?search_query={keyword.replace(' ', '+')}"
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                ns = {"media": "http://search.yahoo.com/mrss/"}
                for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry")[:3]:
                    title = entry.find("{http://www.w3.org/2005/Atom}title")
                    stories.append({
                        "title": title.text if title is not None else "",
                        "text": "",
                        "score": 80,
                        "source": "YouTube"
                    })
        return stories
    except Exception as e:
        print(f"YouTube trending error: {e}")
        return []


# ============================================================
# TWITTER/X RSS SCRAPER
# ============================================================
def get_twitter_stories():
    try:
        keywords = [
            "building collapse",
            "demolition",
            "construction accident"
        ]
        stories = []
        for keyword in keywords:
            # Using Nitter RSS (Twitter mirror, no API needed)
            url = f"https://nitter.poast.org/search/rss?q={keyword.replace(' ', '+')}&f=tweets"
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                for item in root.findall(".//item")[:3]:
                    title = item.find("title")
                    description = item.find("description")
                    stories.append({
                        "title": title.text if title is not None else "",
                        "text": description.text[:300] if description is not None else "",
                        "score": 85,
                        "source": "Twitter/X"
                    })
        return stories
    except Exception as e:
        print(f"Twitter/X error: {e}")
        return []

# ============================================================
# AI STORY SCORER + PICKER
# ============================================================
def score_and_pick_best_story(stories):
    if not stories:
        return generate_fictional_story()

    stories_text = ""
    for i, story in enumerate(stories[:20]):
        stories_text += f"{i+1}. [{story['source']}] {story['title']} — {story['text'][:200]}\n\n"

    prompt = f"""You are a viral content expert for a channel called "Last Seconds Bodycam" about building demolitions, collapses, abandoned buildings and rescue stories.

Here are real stories found today:

{stories_text}

Your job:
1. Score each story from 1-10 on viral potential (dramatic, visual, emotional, surprising)
2. Pick the BEST one
3. If none score above 6, create a fictional but plausible story instead

Return ONLY a valid JSON object, no extra text, no markdown:
{{
    "chosen_story": "full story title and details here",
    "source": "where it came from or AI Generated",
    "viral_score": 8,
    "emotional_angle": "one of: animal_rescue, human_rescue, worker_survival, urban_explorer, homeless_person",
    "location": "city and country",
    "building_type": "type of building"
}}"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )

    try:
        content = response.choices[0].message.content.strip()
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        result = json.loads(content.strip())
        return result
    except Exception as e:
        print(f"JSON parse error: {e}")
        return generate_fictional_story()

# ============================================================
# FICTIONAL STORY GENERATOR (backup)
# ============================================================
def generate_fictional_story():
    prompt = """Create a fictional but completely plausible demolition or building collapse story for a viral short video channel called "Last Seconds Bodycam".

Return ONLY a valid JSON object, no extra text, no markdown:
{
    "chosen_story": "detailed story description here",
    "source": "AI Generated",
    "viral_score": 8,
    "emotional_angle": "one of: animal_rescue, human_rescue, worker_survival, urban_explorer, homeless_person",
    "location": "real city and country",
    "building_type": "type of building"
}

Make it dramatic, emotional and believable. Use real city names."""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9
    )

    try:
        content = response.choices[0].message.content.strip()
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        result = json.loads(content.strip())
        return result
    except:
        return {
            "chosen_story": "A condemned 1960s apartment building in Detroit was scheduled for demolition when workers discovered a dog trapped inside",
            "source": "AI Generated",
            "viral_score": 9,
            "emotional_angle": "animal_rescue",
            "location": "Detroit, USA",
            "building_type": "apartment building"
        }

# ============================================================
# MAIN FUNCTION
# ============================================================
def find_best_story():
    print("🔍 Searching for the best story...")

    google_stories = get_google_news()
    print(f"✅ Google News: {len(google_stories)} stories found")

    bing_stories = get_bing_news()
    print(f"✅ Bing News: {len(bing_stories)} stories found")

    youtube_stories = get_youtube_trending()
    print(f"✅ YouTube Trending: {len(youtube_stories)} stories found")

    twitter_stories = get_twitter_stories()
    print(f"✅ Twitter/X: {len(twitter_stories)} stories found")

    all_stories = google_stories + bing_stories + youtube_stories + twitter_stories
    print(f"📊 Total stories: {len(all_stories)} — picking the best one...")

    best_story = score_and_pick_best_story(all_stories)

    print(f"\n🏆 BEST STORY CHOSEN:")
    print(f"📍 Location: {best_story.get('location')}")
    print(f"🏢 Building: {best_story.get('building_type')}")
    print(f"🎭 Emotional angle: {best_story.get('emotional_angle')}")
    print(f"⭐ Viral score: {best_story.get('viral_score')}/10")
    print(f"📰 Source: {best_story.get('source')}")
    print(f"📖 Story: {best_story.get('chosen_story')[:200]}...")

    return best_story

if __name__ == "__main__":
    story = find_best_story()

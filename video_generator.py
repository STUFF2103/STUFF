import os
import random
import requests
from dotenv import load_dotenv

load_dotenv()

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")

# ============================================================
# SEARCH KEYWORDS PER EMOTIONAL ANGLE
# ============================================================
SEARCH_KEYWORDS = {
    "animal_rescue": [
        "building demolition",
        "construction site",
        "abandoned building",
        "building collapse",
        "demolition explosion"
    ],
    "human_rescue": [
        "building demolition",
        "emergency rescue",
        "building collapse",
        "construction accident",
        "demolition site"
    ],
    "worker_survival": [
        "construction site workers",
        "building demolition",
        "dangerous construction",
        "demolition explosion",
        "building collapse"
    ],
    "urban_explorer": [
        "abandoned building interior",
        "abandoned building",
        "derelict building",
        "abandoned factory",
        "urban exploration"
    ],
    "homeless_person": [
        "abandoned building",
        "derelict building",
        "building demolition",
        "condemned building",
        "abandoned house"
    ]
}

# ============================================================
# FETCH VIDEOS FROM PEXELS
# ============================================================
def fetch_pexels_videos(emotional_angle, num_clips=4):
    print(f"\n🎥 Fetching footage from Pexels...")
    
    keywords = SEARCH_KEYWORDS.get(emotional_angle, SEARCH_KEYWORDS["human_rescue"])
    random.shuffle(keywords)
    
    headers = {"Authorization": PEXELS_API_KEY}
    videos = []

    for keyword in keywords:
        if len(videos) >= num_clips:
            break
            
        url = f"https://api.pexels.com/videos/search"
        params = {
            "query": keyword,
            "per_page": 5,
            "orientation": "portrait",  # Vertical for TikTok/Reels
            "size": "medium"
        }

        try:
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                for video in data.get("videos", []):
                    # Get the best quality video file
                    video_files = video.get("video_files", [])
                    # Filter for HD portrait videos
                    hd_files = [f for f in video_files if f.get("quality") in ["hd", "sd"] and f.get("height", 0) > f.get("width", 0)]
                    
                    if not hd_files:
                        hd_files = video_files
                    
                    if hd_files:
                        best_file = hd_files[0]
                        videos.append({
                            "url": best_file.get("link"),
                            "width": best_file.get("width"),
                            "height": best_file.get("height"),
                            "duration": video.get("duration"),
                            "keyword": keyword
                        })
                        
                        if len(videos) >= num_clips:
                            break
                            
                print(f"✅ '{keyword}': found footage")
            else:
                print(f"⚠️ '{keyword}': no results")
                
        except Exception as e:
            print(f"❌ Pexels error for '{keyword}': {e}")

    return videos

# ============================================================
# DOWNLOAD VIDEO CLIPS
# ============================================================
def download_clips(videos, output_dir="clips"):
    os.makedirs(output_dir, exist_ok=True)
    downloaded = []

    print(f"\n⬇️ Downloading {len(videos)} clips...")

    for i, video in enumerate(videos):
        output_path = os.path.join(output_dir, f"clip_{i+1}.mp4")
        try:
            response = requests.get(video["url"], stream=True, timeout=30)
            if response.status_code == 200:
                with open(output_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                downloaded.append(output_path)
                print(f"✅ Clip {i+1} downloaded ({video.get('keyword')})")
            else:
                print(f"❌ Failed to download clip {i+1}")
        except Exception as e:
            print(f"❌ Download error clip {i+1}: {e}")

    return downloaded

# ============================================================
# MAIN FUNCTION
# ============================================================
def generate_video(story, script_data, output_dir="clips"):
    emotional_angle = story.get("emotional_angle", "human_rescue")
    
    # Fetch videos from Pexels
    videos = fetch_pexels_videos(emotional_angle, num_clips=4)
    
    if not videos:
        print("❌ No videos found on Pexels")
        return None
    
    print(f"\n📦 Found {len(videos)} clips total")
    
    # Download the clips
    downloaded_clips = download_clips(videos, output_dir)
    
    if not downloaded_clips:
        print("❌ Failed to download any clips")
        return None
    
    print(f"\n🎉 Successfully downloaded {len(downloaded_clips)} clips!")
    return downloaded_clips

# ============================================================
# TEST
# ============================================================
if __name__ == "__main__":
    test_story = {
        "chosen_story": "A condemned apartment building in Detroit was scheduled for demolition when workers discovered a dog trapped inside",
        "emotional_angle": "animal_rescue",
        "location": "Detroit, USA",
        "building_type": "apartment building"
    }

    test_script = {
        "voice_style": "casual_energetic",
        "suggested_music_mood": "suspenseful"
    }

    clips = generate_video(test_story, test_script)
    
    if clips:
        print(f"\n✅ Clips ready for assembly:")
        for clip in clips:
            print(f"  📹 {clip}")

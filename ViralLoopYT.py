#!/usr/bin/env python
# coding: utf-8

import os
import re
import time
import json
import random
import shutil
import urllib.parse
import subprocess
from datetime import datetime

import requests
import instaloader
from gtts import gTTS
from huggingface_hub import InferenceClient

from google.oauth2.credentials import Credentials
import googleapiclient.discovery
from googleapiclient.http import MediaFileUpload

# =========================================================
# 🔐 ENVIRONMENT VARIABLES (GitHub Secrets)
# =========================================================

REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET")
YT_TOKEN = os.getenv("YT_TOKEN")

if not all([REDIS_URL, REDIS_TOKEN, HF_TOKEN, YT_CLIENT_SECRET, YT_TOKEN]):
    raise RuntimeError("❌ One or more required environment variables are missing")

# =========================================================
# 🧠 REDIS SETUP (UNCHANGED LOGIC)
# =========================================================

HEADERS = {"Authorization": f"Bearer {REDIS_TOKEN}"}
REDIS_SET_KEY = "uploaded_reels"


def is_already_uploaded(reel_id: str) -> bool:
    reel_id = urllib.parse.quote(reel_id)

    r = requests.get(
        f"{REDIS_URL}/sismember/{REDIS_SET_KEY}/{reel_id}",
        headers=HEADERS,
        timeout=10
    )
    r.raise_for_status()
    result = r.json().get("result", 0)

    print(f"🧠 Redis check {reel_id}: {result}")
    return result == 1


def mark_as_uploaded(reel_id: str):
    reel_id = urllib.parse.quote(reel_id)

    r = requests.post(
        f"{REDIS_URL}/sadd/{REDIS_SET_KEY}/{reel_id}",
        headers=HEADERS,
        timeout=10
    )
    r.raise_for_status()


# =========================================================
# 📥 INSTAGRAM REEL DOWNLOAD
# =========================================================

import requests
import random
import time
import os
import shutil
import subprocess
from datetime import datetime

# Clean old files
if os.path.exists("reels"):
    shutil.rmtree("reels")
os.makedirs("reels", exist_ok=True)

PUBLIC_PAGES = ["titikshaa.singh"]

APIFY_TOKEN = "apify_api_NDaycS1LGgFIWEvRKvqZc0JpRZAFgk4o3XES"  # ⚠️ Replace with your token

def get_video_duration(video_path):
    """Extract video duration using ffprobe"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return float(result.stdout.decode().strip())

def is_already_uploaded(shortcode):
    """Check if reel was already uploaded (integrate with your Redis)"""
    # TODO: Replace with your actual Redis check
    # Example: return redis_client.exists(f"uploaded:{shortcode}")
    return False

def mark_as_uploaded(shortcode):
    """Mark reel as uploaded in Redis"""
    # TODO: Replace with your actual Redis save
    # Example: redis_client.set(f"uploaded:{shortcode}", 1)
    pass

def fetch_reels_from_apify(username):
    """Fetch reels from Instagram using Apify API"""
    url = "https://api.apify.com/v2/acts/apify~instagram-scraper/run-sync-get-dataset-items"
    
    payload = {
        "directUrls": [f"https://www.instagram.com/{username}/"],
        "resultsType": "posts",
        "resultsLimit": 20,  # Fetch more to have a pool
        "searchType": "hashtag",
        "searchLimit": 1
    }
    
    params = {"token": APIFY_TOKEN}
    
    print(f"📡 Fetching reels from @{username} via Apify...")
    
    response = requests.post(url, json=payload, params=params, timeout=120)
    
    if response.status_code != 201:
        raise Exception(f"Apify API error: {response.status_code} - {response.text}")
    
    data = response.json()
    
    # Filter only video posts
    video_posts = [item for item in data if item.get("type") == "Video"]
    
    print(f"✅ Found {len(video_posts)} video posts")
    return video_posts

def download_video(video_url, output_path):
    """Download video file from URL"""
    print(f"⬇️ Downloading video...")
    response = requests.get(video_url, stream=True, timeout=60)
    response.raise_for_status()
    
    with open(output_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    
    print(f"✅ Video downloaded: {output_path}")

def download_one_reel():
    """Main function matching your original logic"""
    
    # 1️⃣ Select random page
    page = random.choice(PUBLIC_PAGES)
    print("🎯 Selected page:", page)
    
    # 2️⃣ Fetch video posts from Apify
    video_posts = fetch_reels_from_apify(page)
    
    if not video_posts:
        raise Exception("❌ No video posts found")
    
    # 3️⃣ Shuffle pool to randomize attempts
    random.shuffle(video_posts)
    
    selected_post = None
    
    # 4️⃣ Find first non-uploaded reel
    for post in video_posts:
        shortcode = post.get("shortCode")
        if not is_already_uploaded(shortcode):
            selected_post = post
            break
        else:
            print(f"⏭️ Skipping already uploaded reel: {shortcode}")
    
    # 5️⃣ If ALL reels are already uploaded
    if not selected_post:
        raise Exception("❌ All reels in this page are already uploaded")
    
    print("🎬 Selected NEW reel:", selected_post.get("shortCode"))
    
    # 6️⃣ Download the selected reel
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = os.path.join("reels", f"reel_{timestamp}.mp4")
    caption_path = os.path.join("reels", f"caption_{timestamp}.txt")
    
    video_url = selected_post.get("videoUrl")
    if not video_url:
        raise Exception("❌ Video URL not found in post data")
    
    download_video(video_url, video_path)
    time.sleep(2)
    
    # 7️⃣ Save caption
    caption = selected_post.get("caption", "")
    with open(caption_path, 'w', encoding='utf-8') as f:
        f.write(caption)
    print(f"✅ Caption saved as: caption_{timestamp}.txt")
    
    # 8️⃣ Mark reel as uploaded in Redis
    mark_as_uploaded(selected_post.get("shortCode"))
    print("🧠 Saved reel ID to Redis:", selected_post.get("shortCode"))
    
    # 9️⃣ Get video duration
    duration = get_video_duration(video_path)
    
    return video_path, page, duration


# ========== MAIN EXECUTION ==========
if __name__ == "__main__":
    VIDEO_FILE, SOURCE_PAGE, DURATION = download_one_reel()
    
    print("\n" + "="*50)
    print("✅ Downloaded ONE video:", VIDEO_FILE)
    print(f"📊 Reel duration: {DURATION:.2f} seconds")
    print(f"📍 Source page: @{SOURCE_PAGE}")
    print("="*50)

import os

HF_TOKEN = os.getenv("HF_TOKEN")

print("HF_TOKEN exists:", HF_TOKEN is not None)
print("HF_TOKEN length:", len(HF_TOKEN) if HF_TOKEN else 0)
print("HF_TOKEN prefix:", HF_TOKEN[:6] + "..." if HF_TOKEN else "None")



# =========================================================
# 🤖 HUGGINGFACE SCRIPT GENERATION
# =========================================================
import re
from huggingface_hub import InferenceClient

# FREE MODEL - No restrictions
MODEL_ID = "meta-llama/Llama-3.2-3B-Instruct"  # OR
# MODEL_ID = "google/gemma-2-2b-it"  # OR
# MODEL_ID = "Qwen/Qwen2.5-3B-Instruct"

client = InferenceClient(
    model=MODEL_ID,
    api_key=HF_TOKEN,  # Still need a free HF token
)

def generate_script_hf(insta_caption):
    try:
        completion = client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Create a viral video hook and short spoken script.\n\n"
                        f"Instagram caption:\n\"{insta_caption}\"\n\n"
                        "Rules:\n"
                        "- Hook: max 6 words\n"
                        "- Script: max 30 words\n"
                        "- Simple spoken English\n"
                        "- No emojis, no hashtags, no brand promotions\n\n"
                        "Return ONLY in this format:\n"
                        "Hook: ...\n"
                        "Script: ..."
                    )
                }
            ],
            max_tokens=120,
            temperature=0.7,
        )

        text = completion.choices[0].message.content

        hook_part = re.search(r"Hook:(.*?)Script:", text, re.S | re.I)
        script_part = re.search(r"Script:(.*)", text, re.S | re.I)

        hook = hook_part.group(1).strip() if hook_part else "Check this out"
        script = script_part.group(1).strip() if script_part else "This clip surprised everyone watching."

        print("✅ HF Chat Completion API called successfully")
        return hook[:50], script[:120]

    except Exception as e:
        print(f"⚠️ HF API error: {e}")
        return "Check this out", "This clip surprised everyone watching."



# =========================================================
# 🎬 VOICE + VIDEO MERGE
# =========================================================

print("🎬 Merging Voice and Video (HF-powered)...")

WATERMARK = "🍫"

# 1. Locate caption file
def find_latest_caption():
    captions = [
        os.path.join("reels", f)
        for f in os.listdir("reels")
        if f.startswith("caption_") and f.endswith(".txt")
    ]
    return max(captions, key=os.path.getmtime) if captions else None


caption_file = find_latest_caption()

if caption_file and os.path.exists(caption_file):
    with open(caption_file, "r", encoding="utf-8") as f:
        actual_caption = f.read().strip()
else:
    actual_caption = "Check out this amazing satisfying moment!"

# 2. Generate script
_, SCRIPT = generate_script_hf(actual_caption)

# 3. Generate voice
gTTS(text=SCRIPT, lang="en").save("voice.mp3")

# 4. Merge voice + video + TRANSPARENT EMOJI WATERMARK
subprocess.run([
    "ffmpeg", "-y",
    "-i", VIDEO_FILE,
    "-i", "voice.mp3",
    "-filter_complex",
    # Audio mix
    "[0:a]volume=0.3[a_orig];"
    "[1:a]volume=2.0[a_voice];"
    "[a_orig][a_voice]amix=inputs=2:duration=first[outa];"
    # Bottom-right transparent watermark with emoji
    f"[0:v]drawtext=text='{WATERMARK}':"
    "fontfile=/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf:"
    "fontsize=38:"
    "fontcolor=white@0.55:"
    "x=w-tw-30:y=h-th-30[outv]",
    "-map", "[outv]",
    "-map", "[outa]",
    "-c:v", "libx264",
    "-preset", "ultrafast",
    "final_short.mp4"
])

print("\n🏆 SUCCESS: final_short.mp4 generated with transparent emoji watermark.")


# =========================================================
# 📤 YOUTUBE UPLOAD
# =========================================================

with open("client_secret.json", "w") as f:
    f.write(YT_CLIENT_SECRET)

with open("token.json", "w") as f:
    f.write(YT_TOKEN)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def get_youtube_service():
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    return googleapiclient.discovery.build("youtube", "v3", credentials=creds)


def upload_video(video_path, title, description, tags):
    youtube = get_youtube_service()

    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "22"
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        },
        media_body=MediaFileUpload(video_path, resumable=True)
    )

    response = request.execute()
    print("✅ Uploaded:", response["id"])


upload_video(
    "final_short.mp4",
    "Viral Video #shorts",
    "Watch till the end! #shorts",
    ["shorts", "viral"]
)

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

if os.path.exists("reels"):
    shutil.rmtree("reels")
os.makedirs("reels", exist_ok=True)

PUBLIC_PAGES = ["our.littlejoys"]

L = instaloader.Instaloader(
    download_pictures=False,
    download_video_thumbnails=False,
    save_metadata=False,
    compress_json=False
)


def get_video_duration(video_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return float(result.stdout.decode().strip())


def download_one_reel():
    page = random.choice(PUBLIC_PAGES)
    print("Selected page:", page)

    profile = instaloader.Profile.from_username(L.context, page)

    video_posts = []
    for post in profile.get_posts():
        if post.is_video:
            video_posts.append(post)
        if len(video_posts) >= 15:
            break

    random.shuffle(video_posts)

    selected_post = None
    for post in video_posts:
        if not is_already_uploaded(post.shortcode):
            selected_post = post
            break

    if not selected_post:
        raise Exception("❌ All reels already uploaded")

    L.download_post(selected_post, target="reels")
    time.sleep(8)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = None

    for f in os.listdir("reels"):
        old = os.path.join("reels", f)
        if f.endswith(".mp4"):
            video_path = os.path.join("reels", f"reel_{timestamp}.mp4")
            os.rename(old, video_path)
        elif f.endswith(".txt"):
            os.rename(old, os.path.join("reels", f"caption_{timestamp}.txt"))

    if not video_path:
        raise Exception("Downloaded video not found")

    mark_as_uploaded(selected_post.shortcode)
    duration = get_video_duration(video_path)

    return video_path, page, duration


VIDEO_FILE, SOURCE_PAGE, DURATION = download_one_reel()
print("Downloaded:", VIDEO_FILE, "Duration:", DURATION)

print(HF_TOKEN)


# =========================================================
# 🤖 HUGGINGFACE SCRIPT GENERATION
# =========================================================

MODEL_ID = "mistralai/Mistral-7B-Instruct-v0.2"

client = InferenceClient(
    model=MODEL_ID,
    api_key=HF_TOKEN,   # must be valid (paid endpoint or allowed model)
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

def find_latest_caption():
    captions = [
        os.path.join("reels", f)
        for f in os.listdir("reels")
        if f.startswith("caption_") and f.endswith(".txt")
    ]
    return max(captions, key=os.path.getmtime) if captions else None


caption_file = find_latest_caption()
if caption_file:
    with open(caption_file, "r", encoding="utf-8") as f:
        caption_text = f.read().strip()
else:
    caption_text = "Check out this amazing moment!"

_, SCRIPT = generate_script_hf(caption_text)

gTTS(text=SCRIPT, lang="en").save("voice.mp3")

subprocess.run([
    "ffmpeg", "-y",
    "-i", VIDEO_FILE,
    "-i", "voice.mp3",
    "-filter_complex",
    "[0:a]volume=0.3[a0];[1:a]volume=2.0[a1];[a0][a1]amix=inputs=2[outa];"
    "[0:v]drawtext=text='🍫':fontfile=/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf:"
    "fontsize=38:fontcolor=white@0.55:x=w-tw-30:y=h-th-30[outv]",
    "-map", "[outv]",
    "-map", "[outa]",
    "-c:v", "libx264",
    "-preset", "ultrafast",
    "final_short.mp4"
])


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

#!/usr/bin/env python
# coding: utf-8

import os
import re
import random
import shutil
import urllib.parse
import subprocess
from datetime import datetime

import requests
from gtts import gTTS
from huggingface_hub import InferenceClient

from google.oauth2.credentials import Credentials
import googleapiclient.discovery
from googleapiclient.http import MediaFileUpload

# =========================================================
# 🔐 ENVIRONMENT VARIABLES
# =========================================================

REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET")
YT_TOKEN = os.getenv("YT_TOKEN")
APIFY_TOKEN = os.getenv("APIFY_TOKEN")

print("REDIS_URL:", bool(REDIS_URL))
print("REDIS_TOKEN:", bool(REDIS_TOKEN))
print("HF_TOKEN:", bool(HF_TOKEN))
print("YT_CLIENT_SECRET:", bool(YT_CLIENT_SECRET))
print("YT_TOKEN:", bool(YT_TOKEN))
print("APIFY_TOKEN:", bool(APIFY_TOKEN))


if not all([REDIS_URL, REDIS_TOKEN, HF_TOKEN, YT_CLIENT_SECRET, YT_TOKEN, APIFY_TOKEN]):
    raise RuntimeError("❌ One or more required environment variables are missing")

# =========================================================
# 🧠 REDIS
# =========================================================

HEADERS = {"Authorization": f"Bearer {REDIS_TOKEN}"}
REDIS_SET_KEY = "uploaded_reels"

def is_already_uploaded(reel_id: str) -> bool:
    reel_id = urllib.parse.quote(reel_id)
    r = requests.get(f"{REDIS_URL}/sismember/{REDIS_SET_KEY}/{reel_id}", headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json().get("result", 0) == 1

def mark_as_uploaded(reel_id: str):
    reel_id = urllib.parse.quote(reel_id)
    r = requests.post(f"{REDIS_URL}/sadd/{REDIS_SET_KEY}/{reel_id}", headers=HEADERS, timeout=10)
    r.raise_for_status()

# =========================================================
# 📥 APIFY INSTAGRAM REELS
# =========================================================

PUBLIC_PAGES = ["titikshaa.singh"]

def fetch_reels_from_apify(username):
    url = "https://api.apify.com/v2/acts/apify~instagram-scraper/run-sync-get-dataset-items"
    payload = {
        "directUrls": [f"https://www.instagram.com/{username}/"],
        "resultsType": "posts",
        "resultsLimit": 20
    }
    response = requests.post(url, json=payload, params={"token": APIFY_TOKEN}, timeout=120)
    response.raise_for_status()
    return [item for item in response.json() if item.get("type") == "Video"]

def download_video(url, out):
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    with open(out, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)

def get_video_duration(video_path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
    )
    return float(result.stdout.decode().strip())

def download_one_reel():
    if os.path.exists("reels"):
        shutil.rmtree("reels")
    os.makedirs("reels", exist_ok=True)

    page = random.choice(PUBLIC_PAGES)
    posts = fetch_reels_from_apify(page)
    random.shuffle(posts)

    post = next(p for p in posts if not is_already_uploaded(p["shortCode"]))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = f"reels/reel_{ts}.mp4"
    caption_path = f"reels/caption_{ts}.txt"

    download_video(post["videoUrl"], video_path)

    with open(caption_path, "w", encoding="utf-8") as f:
        f.write(post.get("caption", ""))

    mark_as_uploaded(post["shortCode"])
    duration = get_video_duration(video_path)

    print("✅ Downloaded reel:", video_path)
    return video_path, caption_path, page, duration

# =========================================================
# 🤖 HUGGINGFACE (SCRIPT + METADATA)
# =========================================================

client = InferenceClient(model="meta-llama/Llama-3.2-3B-Instruct", api_key=HF_TOKEN)

def generate_script_hf(caption):
    completion = client.chat.completions.create(
        messages=[{"role": "user", "content": caption}],
        max_tokens=120,
        temperature=0.7
    )
    text = completion.choices[0].message.content
    return text[:120]

def generate_metadata_hf(insta_caption):
    completion = client.chat.completions.create(
        messages=[{"role": "user", "content": f"Create YouTube Shorts title, description and tags for:\n{insta_caption}"}],
        max_tokens=200,
        temperature=0.8
    )
    text = completion.choices[0].message.content
    return "Viral Video #shorts", "Watch till the end! #shorts", ["shorts", "viral"]

# =========================================================
# 🎬 MERGE VIDEO + VOICE
# =========================================================

VIDEO_FILE, CAPTION_FILE, SOURCE_PAGE, DURATION = download_one_reel()

with open(CAPTION_FILE, "r", encoding="utf-8") as f:
    ACTUAL_CAPTION = f.read().strip() or "Amazing moment"

SCRIPT = generate_script_hf(ACTUAL_CAPTION)
gTTS(text=SCRIPT, lang="en").save("voice.mp3")

FINAL_VIDEO = os.path.abspath("final_short.mp4")

subprocess.run([
    "ffmpeg", "-y",
    "-i", VIDEO_FILE,
    "-i", "voice.mp3",
    "-filter_complex",
    "[0:a]volume=0.3[a_orig];"
    "[1:a]volume=2.0[a_voice];"
    "[a_orig][a_voice]amix=inputs=2:duration=first[outa]",
    "-map", "0:v",
    "-map", "[outa]",
    "-c:v", "libx264",
    "-preset", "ultrafast",
    FINAL_VIDEO
], check=True)

if not os.path.exists(FINAL_VIDEO):
    raise RuntimeError("❌ final_short.mp4 was not created")

print("🏆 Final video created:", FINAL_VIDEO)

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
    req = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {"title": title, "description": description, "tags": tags, "categoryId": "22"},
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
        },
        media_body=MediaFileUpload(video_path, resumable=True)
    )
    res = req.execute()
    print("✅ Uploaded: https://youtube.com/watch?v=" + res["id"])

TITLE, DESCRIPTION, TAGS = generate_metadata_hf(ACTUAL_CAPTION)
upload_video(FINAL_VIDEO, TITLE, DESCRIPTION, TAGS)

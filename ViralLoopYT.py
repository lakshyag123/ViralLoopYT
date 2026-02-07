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

if not all([REDIS_URL, REDIS_TOKEN, HF_TOKEN, YT_CLIENT_SECRET, YT_TOKEN]):
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
        stdout=subprocess.PIPE
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

    return video_path, page, duration

# =========================================================
# 🤖 HUGGINGFACE SCRIPT
# =========================================================

client = InferenceClient(model="meta-llama/Llama-3.2-3B-Instruct", api_key=HF_TOKEN)

def generate_script_hf(caption):
    completion = client.chat.completions.create(
        messages=[{"role": "user", "content": caption}],
        max_tokens=120
    )
    text = completion.choices[0].message.content
    return "Check this out", text[:100]


import os
import subprocess
from gtts import gTTS

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


#new changes

def read_caption_text():
    for f in os.listdir("reels"):
        if f.startswith("caption_") and f.endswith(".txt"):
            with open(os.path.join("reels", f), "r", encoding="utf-8") as file:
                text = file.read().strip()
                return text if text else None
    return None

CAPTION_TEXT = read_caption_text()

print("📄 Caption text loaded:\n", CAPTION_TEXT)


import os
from google.oauth2.credentials import Credentials
import googleapiclient.discovery
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
# TOKEN_FILE = "token.json"
CLIENT_SECRET_FILE = "/content/drive/MyDrive/youtube_secrets/client_secret.json"

def get_youtube_service():
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    return googleapiclient.discovery.build(
        "youtube", "v3", credentials=creds
    )

def upload_video(
    video_path,
    title,
    description,
    tags,
    privacy_status="public"
):
    youtube = get_youtube_service()

    request_body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": "22"  # People & Blogs (good for Shorts)
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(
        video_path,
        chunksize=-1,
        resumable=True
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=media
    )

    response = request.execute()
    video_id = response["id"]
    print("✅ Uploaded video URL: https://www.youtube.com/watch?v=" + video_id)
    return response["id"]



import re
from huggingface_hub import InferenceClient


MODEL_ID = "meta-llama/Llama-3.2-3B-Instruct"

client = InferenceClient(
    model=MODEL_ID,
    api_key=HF_TOKEN
)


def default_metadata():
    return (
        "Viral Video #shorts",
        "Watch till the end! #shorts",
        ["shorts", "viral"]
    )


def generate_metadata_hf(insta_caption):
    try:
        completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return ONLY in this format:\n"
                        "Title: ...\n"
                        "Description: ...\n"
                        "Tags: ..."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        "Create YouTube Shorts metadata.\n\n"
                        f"Instagram caption:\n\"{insta_caption}\"\n\n"
                        "Rules:\n"
                        "- Title < 60 characters and include #shorts\n"
                        "- Description: detailed description with trending and latest viral hashtags\n"
                        "- Tags: comma separated, max 10\n"
                        "- No emojis"
                    )
                }
            ],
            max_tokens=300,
            temperature=0.9,
        )

        text = completion.choices[0].message.content

        # 🔎 Regex parsing (same logic as your original)
        title_match = re.search(r"Title:(.*?)Description:", text, re.S | re.I)
        desc_match = re.search(r"Description:(.*?)Tags:", text, re.S | re.I)
        tags_match = re.search(r"Tags:(.*)", text, re.S | re.I)

        title = title_match.group(1).strip() if title_match else "Viral Video #shorts"
        description = desc_match.group(1).strip() if desc_match else "Check this out! #shorts"
        tags_raw = tags_match.group(1).strip() if tags_match else "shorts,viral"

        tags = [t.strip() for t in tags_raw.split(",") if t.strip()][:10]

        print("✅ HF Metadata API called successfully")
        return title[:60], description[:200], tags

    except Exception as e:
        print(f"⚠️ HF Metadata Error: {e}")
        return default_metadata()



VIDEO_FILE = "final_short.mp4"

#LLM
TITLE, DESCRIPTION, TAGS = generate_metadata_hf(SCRIPT)

print("🎬 TITLE:", TITLE)
print("📝 DESCRIPTION:", DESCRIPTION)
print("🏷️ TAGS:", TAGS)

#Manual
# TITLE = "New Viral Video"
# DESCRIPTION = "Watch till the end! #shorts"
# TAGS = ["shorts", "satisfying", "viral"]

# YT Upload Method
upload_video(
    video_path=VIDEO_FILE,
    title=TITLE,
    description=DESCRIPTION,
    tags=TAGS,
    privacy_status="public"  # or "private"
)


# =========================================================
# 🎬 MERGE VIDEO + VOICE
# =========================================================

# VIDEO_FILE, SOURCE_PAGE, DURATION = download_one_reel()

# caption_files = [f for f in os.listdir("reels") if f.startswith("caption_")]
# with open(os.path.join("reels", caption_files[-1]), "r", encoding="utf-8") as f:
#     caption = f.read()

# _, SCRIPT = generate_script_hf(caption)
# gTTS(text=SCRIPT, lang="en").save("voice.mp3")

# subprocess.run([
#     "ffmpeg", "-y",
#     "-i", VIDEO_FILE,
#     "-i", "voice.mp3",
#     "-filter_complex",
#     "[0:a]volume=0.3[a];[1:a]volume=2.0[b];[a][b]amix=2[outa]",
#     "-map", "0:v",
#     "-map", "[outa]",
#     "-c:v", "libx264",
#     "final_short.mp4"
# ], check=True)

# FINAL_VIDEO_PATH = os.path.abspath("final_short.mp4")
# if not os.path.exists(FINAL_VIDEO_PATH):
#     raise RuntimeError("❌ final_short.mp4 not created")

# # =========================================================
# # 📤 YOUTUBE UPLOAD
# # =========================================================

# with open("client_secret.json", "w") as f:
#     f.write(YT_CLIENT_SECRET)

# with open("token.json", "w") as f:
#     f.write(YT_TOKEN)

# def get_youtube_service():
#     creds = Credentials.from_authorized_user_file("token.json", ["https://www.googleapis.com/auth/youtube.upload"])
#     return googleapiclient.discovery.build("youtube", "v3", credentials=creds)

# def upload_video(path, title, desc, tags):
#     youtube = get_youtube_service()
#     req = youtube.videos().insert(
#         part="snippet,status",
#         body={"snippet": {"title": title, "description": desc, "tags": tags, "categoryId": "22"},
#               "status": {"privacyStatus": "public"}},
#         media_body=MediaFileUpload(path, resumable=True)
#     )
#     print("✅ Uploaded:", req.execute()["id"])

# upload_video(FINAL_VIDEO_PATH, "Viral Short", "Auto uploaded #shorts", ["shorts", "viral"])

#!/usr/bin/env python
# coding: utf-8

import os
import re
import random
import shutil
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

HF_TOKEN = os.getenv("HF_TOKEN")
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET")
YT_TOKEN = os.getenv("TOKEN_MIDNIGHTMOTIVATION")
APIFY_TOKEN = os.getenv("APIFY_TOKEN")

if not all([HF_TOKEN, YT_CLIENT_SECRET, YT_TOKEN, APIFY_TOKEN]):
    raise RuntimeError("❌ Missing env variables")

# =========================================================
# 📥 INSTAGRAM PAGES
# =========================================================

PUBLIC_PAGES = [
    "433",
    "bleacherreportfootball",
    "espnfc",
    "goalglobal",
    "houseofhighlights",
    "tintedvisor"
]

# =========================================================
# 📥 APIFY
# =========================================================

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

def get_view_count(post):
    return post.get("videoViewCount") or post.get("playCount") or post.get("viewCount") or 0

def download_video(url, out):
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    with open(out, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)

# =========================================================
# ✅ DOWNLOAD MULTIPLE REELS (>60s FIX)
# =========================================================

def download_multiple_reels(n=8):  # 🔥 increased to 8
    if os.path.exists("reels"):
        shutil.rmtree("reels")
    os.makedirs("reels", exist_ok=True)

    selected_pages = random.sample(PUBLIC_PAGES, min(n, len(PUBLIC_PAGES)))

    videos, captions = [], []

    for i, page in enumerate(selected_pages):
        print(f"🔎 Fetching from: {page}")

        try:
            posts = fetch_reels_from_apify(page)
            random.shuffle(posts)

            eligible = [p for p in posts if get_view_count(p) > 5000]

            if not eligible:
                continue

            post = eligible[0]

            path = f"reels/reel_{i}.mp4"
            download_video(post["videoUrl"], path)

            videos.append(path)
            captions.append(post.get("caption", ""))

            print(f"✅ Downloaded from {page}")

        except Exception as e:
            print(f"❌ Failed {page}:", e)

    if not videos:
        raise RuntimeError("❌ No reels")

    return videos, captions

# =========================================================
# 🎬 MERGE VIDEOS
# =========================================================

def merge_videos(video_list, output="merged.mp4"):
    with open("inputs.txt", "w") as f:
        for v in video_list:
            f.write(f"file '{os.path.abspath(v)}'\n")

    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", "inputs.txt",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-preset", "ultrafast",
        output
    ], check=True)

    return os.path.abspath(output)

# =========================================================
# 🤖 HUGGINGFACE
# =========================================================

client = InferenceClient(model="meta-llama/Llama-3.2-3B-Instruct", api_key=HF_TOKEN)

def generate_script_hf(caption):
    try:
        res = client.chat.completions.create(
            messages=[{"role": "user", "content": f"Hook + script:\n{caption}"}],
            max_tokens=100
        )
        return "Check this out", res.choices[0].message.content[:100]
    except:
        return "Check this out", "Crazy football moment!"

# =========================================================
# ✅ NEW METADATA (NO SHORTS TAG)
# =========================================================

def generate_metadata_hf(insta_caption):
    try:
        completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Title, Description, Tags"},
                {"role": "user", "content": insta_caption}
            ],
            max_tokens=200,
        )

        text = completion.choices[0].message.content

        title = text.split("\n")[0][:60]
        description = text[:150]

        return (
            title,
            description + "\n\n#football #viral #soccer",
            ["football", "soccer", "viral"]
        )

    except:
        return (
            "Crazy Football Compilation",
            "Watch till the end!",
            ["football"]
        )

# =========================================================
# 🚀 MAIN FLOW
# =========================================================

VIDEO_FILES, CAPTIONS = download_multiple_reels(8)

MERGED_VIDEO = merge_videos(VIDEO_FILES)

VIDEO_FILE = MERGED_VIDEO

ACTUAL_CAPTION = CAPTIONS[0] if CAPTIONS else "Amazing football moment"

HOOK, SCRIPT = generate_script_hf(ACTUAL_CAPTION)

print("🎙️ Script:", SCRIPT)

# =========================================================
# 🎞️ FINAL VIDEO
# =========================================================

FINAL_VIDEO = os.path.abspath("final_video.mp4")

subprocess.run([
    "ffmpeg", "-y",
    "-i", VIDEO_FILE,
    "-c:v", "libx264",
    "-c:a", "copy",
    FINAL_VIDEO
], check=True)

print("🏆 Final video ready:", FINAL_VIDEO)

# =========================================================
# 📤 YOUTUBE UPLOAD
# =========================================================

with open("client_secret.json", "w") as f:
    f.write(YT_CLIENT_SECRET)

with open("token.json", "w") as f:
    f.write(YT_TOKEN)

def get_youtube():
    creds = Credentials.from_authorized_user_file(
        "token.json",
        ["https://www.googleapis.com/auth/youtube.upload"]
    )
    return googleapiclient.discovery.build("youtube", "v3", credentials=creds)

def upload(video, title, desc, tags):
    yt = get_youtube()
    req = yt.videos().insert(
        part="snippet,status",
        body={
            "snippet": {"title": title, "description": desc, "tags": tags},
            "status": {"privacyStatus": "public"}
        },
        media_body=MediaFileUpload(video, resumable=True)
    )
    res = req.execute()
    print("✅ Uploaded:", res["id"])

TITLE, DESC, TAGS = generate_metadata_hf(ACTUAL_CAPTION)

upload(FINAL_VIDEO, TITLE, DESC, TAGS)

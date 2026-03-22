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

# ❌ REDIS DISABLED
# REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL")
# REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")

HF_TOKEN = os.getenv("HF_TOKEN")
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET")
YT_TOKEN = os.getenv("TOKEN_MIDNIGHTMOTIVATION")
APIFY_TOKEN = os.getenv("APIFY_TOKEN")

if not all([HF_TOKEN, YT_CLIENT_SECRET, YT_TOKEN, APIFY_TOKEN]):
    raise RuntimeError("❌ Missing env variables")

# =========================================================
# 🧠 REDIS (DISABLED)
# =========================================================

# HEADERS = {"Authorization": f"Bearer {REDIS_TOKEN}"}
# REDIS_SET_KEY = "uploaded_reels"

# def is_already_uploaded(reel_id: str) -> bool:
#     return False

# def mark_as_uploaded(reel_id: str):
#     pass

# =========================================================
# 📥 APIFY INSTAGRAM REELS
# =========================================================

# ⚠️ FIXED VALID USERNAMES
PUBLIC_PAGES = [
    "433",
    "bleacherreportfootball",
    "espnfc",
    "goalglobal",
    "houseofhighlights",
    "tintedvisor"
]

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
# ❌ OLD SINGLE REEL FUNCTION (COMMENTED)
# =========================================================

# def download_one_reel():
#     ...
#     return video_path

# =========================================================
# ✅ NEW: DOWNLOAD MULTIPLE REELS
# =========================================================

def download_multiple_reels(n=5):
    """
    Download 1 reel from each page (max n pages)
    """

    if os.path.exists("reels"):
        shutil.rmtree("reels")
    os.makedirs("reels", exist_ok=True)

    selected_pages = random.sample(PUBLIC_PAGES, min(n, len(PUBLIC_PAGES)))

    video_paths = []
    captions = []

    for i, page in enumerate(selected_pages):
        print(f"🔎 Fetching from page: {page}")

        try:
            posts = fetch_reels_from_apify(page)
            random.shuffle(posts)

            eligible_posts = [
                p for p in posts
                if get_view_count(p) > 5000
            ]

            if not eligible_posts:
                print(f"⚠️ No valid reels found for {page}")
                continue

            post = eligible_posts[0]

            ts = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{i}"
            video_path = f"reels/reel_{ts}.mp4"

            download_video(post["videoUrl"], video_path)

            video_paths.append(video_path)
            captions.append(post.get("caption", ""))

            print(f"✅ Downloaded from {page}")

        except Exception as e:
            print(f"❌ Failed for {page}:", e)

    if len(video_paths) == 0:
        raise RuntimeError("❌ No reels downloaded from any page")

    return video_paths, captions, selected_pages

# =========================================================
# 🎬 NEW: MERGE VIDEOS
# =========================================================

def merge_videos(video_list, output="merged.mp4"):
    """
    Merge multiple reels into one video
    """

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
            messages=[{"role": "user", "content": f"Hook + script from:\n{caption}"}],
            max_tokens=100
        )
        text = res.choices[0].message.content
        return "Check this out", text[:100]
    except:
        return "Check this out", "Amazing moment"

# ❌ OLD STATIC METADATA (COMMENTED)
# def generate_metadata_hf(caption):
#     return ("Viral Shorts #shorts", "Watch till end! #shorts", ["shorts", "viral"])

# ✅ NEW DYNAMIC METADATA
def generate_metadata_hf(insta_caption):
    try:
        completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Create YouTube Shorts metadata.\n"
                        "Return format:\n"
                        "Title: ...\n"
                        "Description: ...\n"
                        "Tags: ..."
                    )
                },
                {
                    "role": "user",
                    "content": f"Caption:\n{insta_caption}"
                }
            ],
            max_tokens=200,
            temperature=0.8,
        )

        text = completion.choices[0].message.content

        title_match = re.search(r"Title:(.*?)Description:", text, re.S | re.I)
        desc_match = re.search(r"Description:(.*?)Tags:", text, re.S | re.I)
        tags_match = re.search(r"Tags:(.*)", text, re.S | re.I)

        title = title_match.group(1).strip() if title_match else "Crazy Football Moment"
        description = desc_match.group(1).strip() if desc_match else "Watch till the end!"
        tags_raw = tags_match.group(1).strip() if tags_match else "football,shorts"

        tags = [t.strip() for t in tags_raw.split(",") if t.strip()][:10]

        title = f"{title[:50]} ⚽🔥 #shorts"
        description = f"{description[:150]}\n\n#football #shorts #viral #soccer"

        return title, description, tags

    except Exception as e:
        print("⚠️ Metadata error:", e)
        return (
            "Crazy Football Moment ⚽ #shorts",
            "Watch till the end! #shorts",
            ["football", "shorts"]
        )

# =========================================================
# 🚀 MAIN FLOW (UPDATED)
# =========================================================

# ❌ OLD FLOW (COMMENTED)
# VIDEO_FILE, CAPTION_FILE, SOURCE_PAGE, DURATION = download_one_reel()

# ✅ NEW FLOW
VIDEO_FILES, CAPTIONS, SOURCE_PAGE = download_multiple_reels(5)

MERGED_VIDEO = merge_videos(VIDEO_FILES)

VIDEO_FILE = MERGED_VIDEO

# ✅ IMPROVED CAPTION USAGE
ACTUAL_CAPTION = CAPTIONS[0] if CAPTIONS else "Amazing football moment"

HOOK, SCRIPT = generate_script_hf(ACTUAL_CAPTION)

print("🎙️ Script:", SCRIPT)

# =========================================================
# 🔊 VOICE CONFIG
# =========================================================

MERGE_VOICE = False

FINAL_VIDEO = os.path.abspath("final_short.mp4")

if MERGE_VOICE:
    gTTS(text=SCRIPT, lang="en").save("voice.mp3")

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", VIDEO_FILE,
        "-i", "voice.mp3",
        "-filter_complex",
        "[0:a]volume=0.3[a];[1:a]volume=2.0[b];[a][b]amix=inputs=2",
        "-map", "0:v",
        "-map", "[b]",
        "-c:v", "libx264",
        FINAL_VIDEO
    ]
else:
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", VIDEO_FILE,
        "-map", "0:v",
        "-map", "0:a",
        "-c:v", "libx264",
        "-c:a", "copy",
        FINAL_VIDEO
    ]

subprocess.run(ffmpeg_cmd, check=True)

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
            "snippet": {
                "title": title,
                "description": desc,
                "tags": tags
            },
            "status": {"privacyStatus": "public"}
        },
        media_body=MediaFileUpload(video, resumable=True)
    )
    res = req.execute()
    print("✅ Uploaded:", res["id"])

TITLE, DESC, TAGS = generate_metadata_hf(ACTUAL_CAPTION)

upload(FINAL_VIDEO, TITLE, DESC, TAGS)

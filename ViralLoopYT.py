#!/usr/bin/env python
# coding: utf-8

# In[1]:




# 

# In[2]:


# #https://console.upstash.com/redis/ce919edb-411b-47a5-b03c-c5125ee1bb22/details?teamid=0(REDIS)
# import requests
# from google.colab import userdata

# REDIS_URL = userdata.get("UPSTASH_REDIS_REST_URL")
# REDIS_TOKEN = userdata.get("UPSTASH_REDIS_REST_TOKEN")

# if not REDIS_URL or not REDIS_TOKEN:
#     raise Exception("❌ Missing Redis secrets")

# HEADERS = {"Authorization": f"Bearer {REDIS_TOKEN}"}
# REDIS_SET_KEY = "uploaded_reels"

# def is_already_uploaded(reel_id: str) -> bool:
#     r = requests.get(
#         f"{REDIS_URL}/sismember/{REDIS_SET_KEY}/{reel_id}",
#         headers=HEADERS,
#         timeout=10
#     )
#     print(f"response:{r.text}")
#     return r.text == "1"

# def mark_as_uploaded(reel_id: str):
#     requests.post(
#         f"{REDIS_URL}/sadd/{REDIS_SET_KEY}/{reel_id}",
#         headers=HEADERS,
#         timeout=10
#     )


# In[3]:


import requests
import urllib.parse
from google.colab import userdata

REDIS_URL = userdata.get("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = userdata.get("UPSTASH_REDIS_REST_TOKEN")

if not REDIS_URL or not REDIS_TOKEN:
    raise Exception("❌ Missing Redis secrets")

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
    data = r.json()

    # Upstash returns {"result": 0 or 1}
    result = data.get("result", 0)

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


# In[4]:


# def print_all_uploaded_reels():
#     r = requests.get(
#         f"{REDIS_URL}/smembers/{REDIS_SET_KEY}",
#         headers=HEADERS,
#         timeout=10
#     )

#     if r.status_code != 200:
#         raise Exception("❌ Failed to fetch Redis set")

#     reels = r.json().get("result", [])

#     if not reels:
#         print("📭 Redis set is empty (no reels uploaded yet)")
#         return

#     print(f"📦 Total uploaded reels: {len(reels)}\n")
#     for reel in reels:
#         print(reel)

# # Call it
# print_all_uploaded_reels()


# In[5]:


import instaloader
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

PUBLIC_PAGES = ["our.littlejoys"]

L = instaloader.Instaloader(
    download_pictures=False,
    download_video_thumbnails=False,
    save_metadata=False, # Disables JSON, but .txt caption is still created
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

    # 1️⃣ Collect a pool of video posts
    video_posts = []
    MAX_POOL = 15

    for post in profile.get_posts():
        if post.is_video:
            video_posts.append(post)
        if len(video_posts) >= MAX_POOL:
            break

    if not video_posts:
        raise Exception("No video posts found")

    # 2️⃣ Shuffle pool to randomize attempts
    random.shuffle(video_posts)

    selected_post = None

    for post in video_posts:
        if not is_already_uploaded(post.shortcode):
            selected_post = post
            break
        else:
            print(f"⏭️ Skipping already uploaded reel: {post.shortcode}")

    # 3️⃣ If ALL reels are already uploaded
    if not selected_post:
        raise Exception("❌ All reels in this page are already uploaded")

    print("🎯 Selected NEW reel:", selected_post.shortcode)

    # 4️⃣ Download ONLY that reel
    L.download_post(selected_post, target="reels")
    time.sleep(8)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_path = ""

    # 5️⃣ Rename downloaded files
    for f in os.listdir("reels"):
        old_path = os.path.join("reels", f)

        if f.endswith(".mp4") and not f.startswith("reel_"):
            new_video_name = f"reel_{timestamp}.mp4"
            video_path = os.path.join("reels", new_video_name)
            os.rename(old_path, video_path)

        elif f.endswith(".txt") and not f.startswith("caption_"):
            new_txt_name = f"caption_{timestamp}.txt"
            os.rename(old_path, os.path.join("reels", new_txt_name))
            print(f"✅ Caption saved as: {new_txt_name}")

    if not video_path:
        raise Exception("Downloaded video file not found")

    # 6️⃣ Mark reel as uploaded in Redis
    mark_as_uploaded(selected_post.shortcode)
    print("🧠 Saved reel ID to Redis:", selected_post.shortcode)

    duration = get_video_duration(video_path)
    return video_path, page, duration



VIDEO_FILE, SOURCE_PAGE, DURATION = download_one_reel()

print("Downloaded ONE video:", VIDEO_FILE)
print(f"Reel duration: {DURATION:.2f} seconds")



# In[6]:


from google.colab import userdata
HF_TOKEN = userdata.get('HF_TOKEN')


# In[7]:


import re
from huggingface_hub import InferenceClient

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


# In[8]:


# #Manual
# # import os
# # import subprocess
# # from gtts import gTTS

# # # --- 4. VOICE & VIDEO PRODUCTION ---
# # print("🎬 Merging Voice and Video...")

# # # 1. Find the latest caption file
# # caption_file = VIDEO_FILE.replace("reel_", "caption_").replace(".mp4", ".txt")

# # if os.path.exists(caption_file):
# #     with open(caption_file, "r", encoding="utf-8") as f:
# #         actual_caption = f.read().strip()

# #     # DEFINE HOOK: Use the first 5 words of the caption for the visual overlay
# #     words = actual_caption.split()
# #     HOOK = " ".join(words[:5]) + "..." if len(words) > 5 else actual_caption
# #     print(f"📖 Using caption for voice. Hook for overlay: {HOOK}")
# # else:
# #     # FALLBACK: If txt is missing, use standard defaults
# #     actual_caption = "Check out this amazing satisfying moment!"
# #     HOOK = "Satisfying Discovery!"
# #     print("⚠️ Caption file not found, using generic fallback.")

# # # 2. Generate Voice from the FULL caption
# # gTTS(text=actual_caption, lang='en').save("voice2.mp3")

# # # 3. Merge with FFmpeg (Now HOOK is defined)
# # subprocess.run([
# #     "ffmpeg", "-y",
# #     "-i", VIDEO_FILE,
# #     "-i", "voice2.mp3",
# #     "-filter_complex",
# #     # Audio Mix: Background at 30%, Voice at 200%
# #     "[0:a]volume=0.3[a_orig];[1:a]volume=2.0[a_voice];[a_orig][a_voice]amix=inputs=2:duration=first[outa];"
# #     # Visual Overlay: Uses the HOOK variable we just defined
# #     f"[0:v]drawtext=text='{HOOK}':fontcolor=white:fontsize=30:box=1:boxcolor=black@0.6:x=(w-tw)/2:y=h-th-150[outv]",
# #     "-map", "[outv]",
# #     "-map", "[outa]",
# #     "-c:v", "libx264",
# #     "-preset", "ultrafast",
# #     "final_short2.mp4"
# # ])

# # print("\n🏆 SUCCESS: final_short2.mp4 generated with caption-based text and voice.")

# #LLM
# import os
# import subprocess
# from gtts import gTTS

# print("🎬 Merging Voice and Video (HF-powered)...")

# # 1. Locate caption file
# def find_latest_caption():
#     captions = [
#         os.path.join("reels", f)
#         for f in os.listdir("reels")
#         if f.startswith("caption_") and f.endswith(".txt")
#     ]
#     if not captions:
#         return None
#     # Pick the latest caption file
#     return max(captions, key=os.path.getmtime)


# caption_file = find_latest_caption()

# if caption_file and os.path.exists(caption_file):
#     with open(caption_file, "r", encoding="utf-8") as f:
#         actual_caption = f.read().strip()
#     print(f"📄 Using caption file: {caption_file}")
# else:
#     actual_caption = "Check out this amazing satisfying moment!"
#     print("⚠️ Caption file not found, using fallback")


# # if os.path.exists(caption_file):
# #     with open(caption_file, "r", encoding="utf-8") as f:
# #         actual_caption = f.read().strip()

# #     # DEFINE HOOK: Use the first 5 words of the caption for the visual overlay
# #     words = actual_caption.split()
# #     HOOK = " ".join(words[:5]) + "..." if len(words) > 5 else actual_caption
# # else:
# #     actual_caption = "Check out this amazing satisfying moment!"
# #     print("⚠️ Caption file not found, using fallback")

# # 2. 🔥 CALL YOUR HF API (Hook + Script)
# HOOK, SCRIPT = generate_script_hf(actual_caption)

# print("🎯 HOOK:", HOOK) # the text displayed on the screen
# print("🗣️ SCRIPT:", SCRIPT) # the voice script that is spoken by AI

# # 3. Generate voice from SCRIPT (NOT full caption)
# gTTS(text=SCRIPT, lang="en").save("voice.mp3")

# # 4. Merge voice + video + HOOK overlay
# subprocess.run([
#     "ffmpeg", "-y",
#     "-i", VIDEO_FILE,
#     "-i", "voice.mp3",
#     "-filter_complex",
#     # Audio mix
#     "[0:a]volume=0.3[a_orig];"
#     "[1:a]volume=2.0[a_voice];"
#     "[a_orig][a_voice]amix=inputs=2:duration=first[outa];"
#     # Text overlay using HOOK from LLM
#     f"[0:v]drawtext=text='{HOOK}':"
#     "fontcolor=white:fontsize=30:box=1:boxcolor=black@0.6:"
#     "x=(w-tw)/2:y=h-th-150[outv]",
#     "-map", "[outv]",
#     "-map", "[outa]",
#     "-c:v", "libx264",
#     "-preset", "ultrafast",
#     "final_short.mp4"
# ])

# print("\n🏆 SUCCESS: final_short.mp4 generated using HF Hook + Script.")



# In[9]:


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



# In[10]:


from google.colab import userdata

CLIENT_SECRET_FILE = "client_secret.json"
TOKEN_FILE = "token.json"

client_secret = userdata.get("YT_CLIENT_SECRET")
token_secret = userdata.get("YT_TOKEN")

if not client_secret or not token_secret:
    raise Exception("❌ Missing Colab secrets: YT_CLIENT_SECRET / YT_TOKEN")

with open(CLIENT_SECRET_FILE, "w") as f:
    f.write(client_secret)

with open(TOKEN_FILE, "w") as f:
    f.write(token_secret)

print("✅ Secrets restored from Colab userdata")


# In[11]:




# In[12]:


# #Code to generate token

# import os, json, re
# from google_auth_oauthlib.flow import Flow

# # This allows the use of http (insecure) for the localhost redirect
# os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'


# # 1. SETUP - Use 8090 to avoid the 'node' process conflict
# REDIRECT_URI = "http://localhost:8090/"

# SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


# # 2. CREATE FLOW
# # flow = Flow.from_client_secrets_file(
# #     'client_secret.json',
# #     scopes=SCOPES,
# #     redirect_uri=REDIRECT_URI
# # )

# flow = Flow.from_client_secrets_file(
#     CLIENT_SECRET_FILE,
#     scopes=SCOPES,
#     redirect_uri=REDIRECT_URI
# )

# # 3. GENERATE AUTH URL
# auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
# print(f"1. Click here to authorize: {auth_url}")

# # 4. MANUAL CAPTURE
# print("\nInstructions for Colab:")
# print("After clicking 'Allow', the browser will fail to load a page at 'localhost:8090'.")
# print("Copy the FULL URL from your browser's address bar (starts with http://localhost:8090/...)")
# auth_response = input("\n2. Paste that FULL URL here: ").strip()

# # 5. FETCH AND SAVE PERMANENT TOKEN
# flow.fetch_token(authorization_response=auth_response)
# with open("token.json", "w") as token:
#     token.write(flow.credentials.to_json())

# print("\n✅ SUCCESS! 'token.json' created using port 8090.")


# In[13]:


def read_caption_text():
    for f in os.listdir("reels"):
        if f.startswith("caption_") and f.endswith(".txt"):
            with open(os.path.join("reels", f), "r", encoding="utf-8") as file:
                text = file.read().strip()
                return text if text else None
    return None

CAPTION_TEXT = read_caption_text()

print("📄 Caption text loaded:\n", CAPTION_TEXT)


# In[14]:


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


# In[15]:


import re
from huggingface_hub import InferenceClient


MODEL_ID = "mistralai/Mistral-7B-Instruct-v0.2"

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



# In[16]:


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


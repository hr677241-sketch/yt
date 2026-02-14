import os
import sys
import json
import time
import subprocess
import yt_dlp
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from title_modifier import modify_title
from description_modifier import modify_description, modify_tags


# ============ CONFIG ============
SOURCE_URL     = os.environ.get("SOURCE_URL", "")
SPEED          = float(os.environ.get("SPEED", "1.05"))
BATCH_SIZE     = int(os.environ.get("BATCH_SIZE", "3"))
PRIVACY        = os.environ.get("PRIVACY", "public")
HISTORY_FILE   = "history.txt"
ORDER          = os.environ.get("ORDER", "oldest")
COOKIES_FILE   = "cookies.txt"


# ============ SETUP COOKIES ============
def setup_cookies():
    cookies = os.environ.get("YOUTUBE_COOKIES", "")
    if not cookies:
        print("⚠️  No YOUTUBE_COOKIES secret found!")
        return False
    with open(COOKIES_FILE, "w") as f:
        f.write(cookies)
    print("🍪 Cookies file created successfully")
    return True


# ============ HISTORY ============
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            return set(l.strip() for l in f if l.strip())
    return set()


def save_history(vid):
    with open(HISTORY_FILE, "a") as f:
        f.write(vid + "\n")


# ============ GET BASE CHANNEL URL ============
def get_channel_base(url):
    """Extract base channel URL from any channel URL format."""
    import re
    # Handle different URL formats
    # https://www.youtube.com/@ChannelName/videos
    # https://www.youtube.com/channel/UCxxxx/videos
    # https://www.youtube.com/c/ChannelName/videos

    # Remove trailing path like /videos or /shorts
    base = re.sub(r'/(videos|shorts|streams|playlists|community|about|featured)/?$', '', url.strip().rstrip('/'))
    return base


# ============ GET ALL VIDEOS + SHORTS ============
def get_all_content(url):
    """
    Fetch ALL videos AND shorts from channel.
    Scans both /videos and /shorts pages.
    """
    base_url = get_channel_base(url)

    videos_url = base_url + "/videos"
    shorts_url = base_url + "/shorts"

    all_content = []
    seen_ids = set()

    # ── Fetch Regular Videos ──
    print(f"\n📹 Scanning regular videos: {videos_url}")
    videos = fetch_playlist(videos_url)
    for v in videos:
        if v['id'] not in seen_ids:
            v['type'] = 'video'
            all_content.append(v)
            seen_ids.add(v['id'])
    print(f"   Found: {len(videos)} regular videos")

    # ── Fetch Shorts/Reels ──
    print(f"\n🎬 Scanning shorts/reels: {shorts_url}")
    shorts = fetch_playlist(shorts_url)
    for s in shorts:
        if s['id'] not in seen_ids:
            s['type'] = 'short'
            all_content.append(s)
            seen_ids.add(s['id'])
    print(f"   Found: {len(shorts)} shorts/reels")

    print(f"\n📊 Total content found: {len(all_content)}")
    print(f"   📹 Videos: {len(videos)}")
    print(f"   🎬 Shorts: {len(shorts)}")

    return all_content


def fetch_playlist(url):
    """Fetch all video entries from a URL."""
    opts = {
        'quiet': True,
        'extract_flat': True,
        'ignoreerrors': True,
    }
    if os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE

    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=False)
            entries = info.get('entries', [])
            result = []
            for e in entries:
                if e and e.get('id'):
                    result.append({
                        'id': e['id'],
                        'url': f"https://www.youtube.com/watch?v={e['id']}",
                        'title': e.get('title', 'Untitled'),
                    })
            return result
    except Exception as ex:
        print(f"   ⚠️  Error scanning {url}: {ex}")
        return []


# ============ DOWNLOAD ============
def download(url, vid):
    os.makedirs("dl", exist_ok=True)
    opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'dl/{vid}.%(ext)s',
        'merge_output_format': 'mp4',
        'quiet': False,
        'retries': 10,
        'fragment_retries': 10,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
    }
    if os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE

    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=True)

        # Detect if short based on duration and aspect ratio
        duration = info.get('duration', 0) or 0
        width = info.get('width', 1920) or 1920
        height = info.get('height', 1080) or 1080
        is_short = (duration <= 60) or (height > width)

        return {
            'id': vid,
            'title': info.get('title', 'Untitled'),
            'desc': info.get('description', ''),
            'tags': info.get('tags', []) or [],
            'file': f'dl/{vid}.mp4',
            'duration': duration,
            'width': width,
            'height': height,
            'is_short': is_short,
        }


# ============ DETECT VIDEO TYPE ============
def detect_type(meta, original_type):
    """
    Double check if content is short or regular video.
    Uses both the URL source and actual video properties.
    """
    # If it came from /shorts page, it's a short
    if original_type == 'short':
        return 'short'

    # If duration <= 60s and vertical, it's a short
    if meta.get('is_short', False):
        return 'short'

    # If vertical aspect ratio
    if meta.get('height', 0) > meta.get('width', 0):
        return 'short'

    return 'video'


# ============ MODIFY VIDEO (Regular) ============
def modify_regular_video(inp, out, speed):
    """Modify regular horizontal video."""
    os.makedirs("out", exist_ok=True)

    vf = ",".join([
        f"setpts=PTS/{speed}",
        "hflip",
        "crop=iw*0.95:ih*0.95",
        "scale=1920:1080",
        "eq=brightness=0.04:contrast=1.06:saturation=1.08",
        "colorbalance=rs=0.03:gs=-0.02:bs=0.04",
        "unsharp=5:5:0.8:5:5:0.4",
    ])

    af = ",".join([
        f"atempo={speed}",
        "asetrate=44100*1.02",
        "aresample=44100",
        "bass=g=3:f=110",
        "equalizer=f=1000:width_type=h:width=200:g=-2",
    ])

    cmd = [
        "ffmpeg", "-y",
        "-i", inp,
        "-filter:v", vf,
        "-filter:a", af,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        out
    ]

    print("🔧 Modifying regular video (anti-copyright)...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FFmpeg stderr: {r.stderr[-1000:]}")
        raise Exception("FFmpeg failed")
    print("✅ Regular video modified")


# ============ MODIFY SHORT/REEL ============
def modify_short_video(inp, out, speed):
    """
    Modify YouTube Short / Reel.
    Keeps VERTICAL format (1080x1920).
    Must stay under 60 seconds.
    """
    os.makedirs("out", exist_ok=True)

    vf = ",".join([
        f"setpts=PTS/{speed}",
        "hflip",
        "crop=iw*0.95:ih*0.95",
        "scale=1080:1920",           # VERTICAL for shorts
        "eq=brightness=0.04:contrast=1.06:saturation=1.08",
        "colorbalance=rs=0.03:gs=-0.02:bs=0.04",
        "unsharp=5:5:0.8:5:5:0.4",
    ])

    af = ",".join([
        f"atempo={speed}",
        "asetrate=44100*1.02",
        "aresample=44100",
        "bass=g=3:f=110",
        "equalizer=f=1000:width_type=h:width=200:g=-2",
    ])

    cmd = [
        "ffmpeg", "-y",
        "-i", inp,
        "-filter:v", vf,
        "-filter:a", af,
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", "59",                  # Force max 59 seconds for shorts
        out
    ]

    print("🔧 Modifying short/reel (anti-copyright, vertical)...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FFmpeg stderr: {r.stderr[-1000:]}")
        raise Exception("FFmpeg failed")
    print("✅ Short/reel modified (vertical 1080x1920)")


# ============ UPLOAD ============
def get_youtube():
    token_str = os.environ.get("YOUTUBE_TOKEN", "")
    if not token_str:
        print("❌ YOUTUBE_TOKEN not set")
        sys.exit(1)

    token = json.loads(token_str)
    creds = Credentials(
        token=token.get('token', ''),
        refresh_token=token['refresh_token'],
        token_uri=token.get('token_uri', 'https://oauth2.googleapis.com/token'),
        client_id=token['client_id'],
        client_secret=token['client_secret'],
    )
    return build("youtube", "v3", credentials=creds)


def upload_video(yt, path, title, desc, tags, privacy):
    body = {
        'snippet': {
            'title': title[:100],
            'description': desc[:5000],
            'tags': tags[:30],
            'categoryId': '22',
        },
        'status': {
            'privacyStatus': privacy,
            'selfDeclaredMadeForKids': False,
        }
    }

    media = MediaFileUpload(
        path,
        mimetype='video/mp4',
        resumable=True,
        chunksize=10 * 1024 * 1024
    )

    req = yt.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    print(f"📤 Uploading: {title}")
    resp = None
    retry = 0

    while resp is None:
        try:
            status, resp = req.next_chunk()
            if status:
                print(f"   Progress: {int(status.progress() * 100)}%")
        except HttpError as e:
            if e.resp.status in [500, 502, 503, 504]:
                retry += 1
                if retry > 10:
                    raise
                time.sleep(2 ** retry)
                continue
            raise
        except Exception:
            retry += 1
            if retry > 10:
                raise
            time.sleep(5)
            continue

    vid_id = resp['id']
    print(f"✅ Uploaded! → https://youtu.be/{vid_id}")
    return vid_id


# ============ MAIN PIPELINE ============
def main():
    print("=" * 60)
    print("🚀 YouTube Automation — VIDEOS + SHORTS/REELS")
    print("=" * 60)

    if not SOURCE_URL:
        print("❌ SOURCE_URL not set!")
        sys.exit(1)

    # Setup cookies
    print("\n🍪 Setting up cookies...")
    setup_cookies()

    history = load_history()
    print(f"📜 Already uploaded: {len(history)} items")

    # Get ALL content (videos + shorts)
    all_content = get_all_content(SOURCE_URL)

    if not all_content:
        print("❌ No content found on channel")
        return

    # Filter out already uploaded
    pending = [v for v in all_content if v['id'] not in history]

    if not pending:
        print("🎉 ALL content already uploaded! Nothing to do.")
        return

    # Sort order
    if ORDER == "oldest":
        pending.reverse()
        print("📋 Order: Oldest first")
    else:
        print("📋 Order: Newest first")

    # Count types
    pending_videos = len([p for p in pending if p.get('type') == 'video'])
    pending_shorts = len([p for p in pending if p.get('type') == 'short'])

    print(f"\n📊 CHANNEL SUMMARY:")
    print(f"   Total content:     {len(all_content)}")
    print(f"   Already uploaded:  {len(history)}")
    print(f"   Remaining:         {len(pending)}")
    print(f"     📹 Videos:       {pending_videos}")
    print(f"     🎬 Shorts:       {pending_shorts}")
    print(f"   This batch:        {min(BATCH_SIZE, len(pending))}")

    batch = pending[:BATCH_SIZE]
    yt = get_youtube()

    success_count = 0
    fail_count = 0
    videos_uploaded = 0
    shorts_uploaded = 0

    for i, v in enumerate(batch):
        try:
            print(f"\n{'=' * 60}")
            type_emoji = "🎬" if v.get('type') == 'short' else "📹"
            type_label = "SHORT/REEL" if v.get('type') == 'short' else "VIDEO"
            print(f"{type_emoji} [{i+1}/{len(batch)}] [{type_label}] {v['title']}")
            print(f"   ID: {v['id']}")
            print(f"{'=' * 60}")

            # ── DOWNLOAD ──
            print("\n⬇️  Downloading...")
            meta = download(v['url'], v['id'])
            file_size = os.path.getsize(meta['file']) / (1024 * 1024)
            print(f"   File size: {file_size:.1f} MB")
            print(f"   Duration: {meta['duration']}s")
            print(f"   Resolution: {meta['width']}x{meta['height']}")

            # ── DETECT TYPE ──
            content_type = detect_type(meta, v.get('type', 'video'))
            print(f"   Detected as: {'🎬 SHORT/REEL' if content_type == 'short' else '📹 REGULAR VIDEO'}")

            # ── MODIFY VIDEO ──
            print("\n⚡ Modifying...")
            out_file = f"out/{v['id']}_mod.mp4"

            if content_type == 'short':
                modify_short_video(meta['file'], out_file, SPEED)
            else:
                modify_regular_video(meta['file'], out_file, SPEED)

            # ── MODIFY TITLE ──
            new_title = modify_title(meta['title'])

            # For shorts: add #Shorts to make YouTube recognize as Short
            if content_type == 'short':
                if '#shorts' not in new_title.lower():
                    # Keep title under 100 chars
                    if len(new_title) <= 91:
                        new_title = new_title + " #Shorts"
                    else:
                        new_title = new_title[:91] + " #Shorts"

            print(f"\n📝 Title:")
            print(f"   BEFORE: {meta['title']}")
            print(f"   AFTER:  {new_title}")

            # ── MODIFY DESCRIPTION ──
            new_desc = modify_description(meta['desc'], new_title)

            # For shorts: add #Shorts at start of description too
            if content_type == 'short':
                if '#shorts' not in new_desc.lower():
                    new_desc = "#Shorts\n\n" + new_desc

            print(f"\n📝 Description:")
            print(f"   BEFORE: {meta['desc'][:60]}...")
            print(f"   AFTER:  {new_desc[:60]}...")

            # ── MODIFY TAGS ──
            new_tags = modify_tags(meta['tags'])

            # For shorts: add shorts-specific tags
            if content_type == 'short':
                shorts_tags = ["shorts", "short", "reels", "viral shorts",
                              "trending shorts", "ytshorts", "youtube shorts"]
                new_tags = new_tags + shorts_tags
                # Remove duplicates
                seen = set()
                unique_tags = []
                for t in new_tags:
                    if t.lower() not in seen:
                        seen.add(t.lower())
                        unique_tags.append(t)
                new_tags = unique_tags[:30]

            print(f"\n🏷️  Tags: {new_tags[:5]}...")

            # ── UPLOAD ──
            print(f"\n📤 Uploading as {'SHORT/REEL' if content_type == 'short' else 'VIDEO'}...")
            upload_video(yt, out_file, new_title, new_desc, new_tags, PRIVACY)

            save_history(v['id'])
            success_count += 1
            if content_type == 'short':
                shorts_uploaded += 1
            else:
                videos_uploaded += 1

            # Cleanup
            if os.path.exists(meta['file']):
                os.remove(meta['file'])
            if os.path.exists(out_file):
                os.remove(out_file)
            print("🗑️  Cleaned up files")

            if i < len(batch) - 1:
                print("⏳ Waiting 30s before next...")
                time.sleep(30)

        except Exception as e:
            print(f"\n❌ ERROR: {e}")
            fail_count += 1
            try:
                for f in [f"dl/{v['id']}.mp4", f"out/{v['id']}_mod.mp4"]:
                    if os.path.exists(f):
                        os.remove(f)
            except:
                pass
            continue

    # Cleanup cookies
    if os.path.exists(COOKIES_FILE):
        os.remove(COOKIES_FILE)

    remaining = len(pending) - success_count
    print(f"\n{'=' * 60}")
    print(f"📊 BATCH SUMMARY")
    print(f"{'=' * 60}")
    print(f"   ✅ Total uploaded:    {success_count}")
    print(f"      📹 Videos:         {videos_uploaded}")
    print(f"      🎬 Shorts/Reels:   {shorts_uploaded}")
    print(f"   ❌ Failed:            {fail_count}")
    print(f"   ⏳ Remaining:         {remaining}")
    if remaining > 0:
        print(f"   ⏰ Next batch:        {min(BATCH_SIZE, remaining)}")
        print(f"   💡 All done in ~{remaining // BATCH_SIZE + 1} more runs")
    else:
        print(f"   🎉 ALL CONTENT UPLOADED!")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

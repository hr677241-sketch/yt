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


# ============ CONFIG ============
SOURCE_URL     = os.environ.get("SOURCE_URL", "")
SPEED          = float(os.environ.get("SPEED", "1.05"))
BATCH_SIZE     = int(os.environ.get("BATCH_SIZE", "3"))      # videos per run
PRIVACY        = os.environ.get("PRIVACY", "public")
TITLE_PREFIX   = os.environ.get("TITLE_PREFIX", "")
TITLE_SUFFIX   = os.environ.get("TITLE_SUFFIX", " | HD")
HISTORY_FILE   = "history.txt"
ORDER          = os.environ.get("ORDER", "oldest")            # oldest or newest


# ============ HISTORY (tracks uploaded videos) ============
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            return set(l.strip() for l in f if l.strip())
    return set()


def save_history(vid):
    with open(HISTORY_FILE, "a") as f:
        f.write(vid + "\n")


# ============ STEP 1: GET ALL VIDEOS FROM CHANNEL ============
def get_all_videos(url):
    """
    Fetch ALL videos from a channel/playlist — no limit.
    Returns complete list of every video on the channel.
    """
    opts = {
        'quiet': True,
        'extract_flat': True,
        'ignoreerrors': True,
    }

    print(f"🔍 Scanning entire channel: {url}")
    print("   (This may take a minute for large channels...)")

    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=False)
        entries = info.get('entries', [])

        all_videos = []
        for e in entries:
            if e and e.get('id'):
                all_videos.append({
                    'id': e['id'],
                    'url': f"https://www.youtube.com/watch?v={e['id']}",
                    'title': e.get('title', 'Untitled'),
                })

        print(f"📊 Total videos found on channel: {len(all_videos)}")
        return all_videos


# ============ STEP 2: DOWNLOAD ============
def download(url, vid):
    os.makedirs("dl", exist_ok=True)
    opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'dl/{vid}.%(ext)s',
        'merge_output_format': 'mp4',
        'quiet': False,
    }
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=True)
        return {
            'id': vid,
            'title': info.get('title', 'Untitled'),
            'desc': info.get('description', ''),
            'tags': info.get('tags', []) or [],
            'file': f'dl/{vid}.mp4',
        }


# ============ STEP 3: MODIFY VIDEO (Anti Copyright) ============
def modify_video(inp, out, speed):
    os.makedirs("out", exist_ok=True)

    # Video filters - all anti-copyright tricks
    vf = ",".join([
        f"setpts=PTS/{speed}",
        "hflip",
        "crop=iw*0.95:ih*0.95",
        "scale=1920:1080",
        "eq=brightness=0.04:contrast=1.06:saturation=1.08",
        "colorbalance=rs=0.03:gs=-0.02:bs=0.04",
        "unsharp=5:5:0.8:5:5:0.4",
    ])

    # Audio filters - break audio fingerprint
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

    print("🔧 Modifying video (anti-copyright)...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FFmpeg stderr: {r.stderr[-1000:]}")
        raise Exception("FFmpeg failed")
    print("✅ Video modified successfully")


# ============ STEP 4: UPLOAD ============
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
                print(f"   Retrying in {2**retry}s...")
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
    print("🚀 YouTube Automation Pipeline — FULL CHANNEL MODE")
    print("=" * 60)

    if not SOURCE_URL:
        print("❌ SOURCE_URL not set!")
        sys.exit(1)

    # Load history of already uploaded videos
    history = load_history()
    print(f"📜 Already uploaded: {len(history)} videos")

    # Get ALL videos from channel
    all_videos = get_all_videos(SOURCE_URL)

    if not all_videos:
        print("❌ No videos found on channel")
        return

    # Filter out already uploaded
    pending = [v for v in all_videos if v['id'] not in history]

    if not pending:
        print("🎉 ALL videos already uploaded! Nothing to do.")
        return

    # Sort order
    if ORDER == "oldest":
        pending.reverse()    # oldest first (bottom of list = oldest)
        print("📋 Order: Oldest first")
    else:
        print("📋 Order: Newest first")

    print(f"📊 Total on channel:  {len(all_videos)}")
    print(f"✅ Already uploaded:  {len(history)}")
    print(f"⏳ Remaining:         {len(pending)}")
    print(f"📦 This batch:        {min(BATCH_SIZE, len(pending))}")

    # Take only BATCH_SIZE for this run
    batch = pending[:BATCH_SIZE]

    # Connect to YouTube
    yt = get_youtube()

    success_count = 0
    fail_count = 0

    for i, v in enumerate(batch):
        try:
            print(f"\n{'=' * 50}")
            print(f"📹 [{i+1}/{len(batch)}] {v['title']}")
            print(f"   ID: {v['id']}")
            print(f"{'=' * 50}")

            # Download
            print("\n⬇️  Downloading...")
            meta = download(v['url'], v['id'])
            file_size = os.path.getsize(meta['file']) / (1024 * 1024)
            print(f"   File size: {file_size:.1f} MB")

            # Modify
            print("\n⚡ Modifying video...")
            out_file = f"out/{v['id']}_mod.mp4"
            modify_video(meta['file'], out_file, SPEED)

            # Change metadata
            new_title = TITLE_PREFIX + meta['title'] + TITLE_SUFFIX
            new_desc = (
                meta['desc'][:1000] + "\n\n"
                "Like & Subscribe for more!\n"
                "#trending #viral"
            )

            # Upload
            print("\n📤 Uploading to Channel B...")
            upload_video(yt, out_file, new_title, new_desc, meta['tags'], PRIVACY)

            # Mark as done
            save_history(v['id'])
            success_count += 1

            # Cleanup disk space immediately
            if os.path.exists(meta['file']):
                os.remove(meta['file'])
            if os.path.exists(out_file):
                os.remove(out_file)
            print("🗑️  Cleaned up files")

            # Small delay between uploads
            if i < len(batch) - 1:
                print("⏳ Waiting 30s before next video...")
                time.sleep(30)

        except Exception as e:
            print(f"\n❌ ERROR: {e}")
            fail_count += 1
            # Cleanup on error
            try:
                for f in [f"dl/{v['id']}.mp4", f"out/{v['id']}_mod.mp4"]:
                    if os.path.exists(f):
                        os.remove(f)
            except:
                pass
            continue

    # Final summary
    remaining = len(pending) - success_count
    print(f"\n{'=' * 60}")
    print(f"📊 BATCH SUMMARY")
    print(f"{'=' * 60}")
    print(f"   ✅ Uploaded:   {success_count}")
    print(f"   ❌ Failed:     {fail_count}")
    print(f"   ⏳ Remaining:  {remaining}")
    if remaining > 0:
        print(f"   ⏰ Next run will process {min(BATCH_SIZE, remaining)} more")
        print(f"   💡 All videos will be done in ~{remaining // BATCH_SIZE + 1} more runs")
    else:
        print(f"   🎉 ALL VIDEOS UPLOADED!")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

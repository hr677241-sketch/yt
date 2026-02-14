import os
import sys
import json
import time
import subprocess
import base64
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
OAUTH_FILE     = "yt_oauth.json"


# ============ SETUP AUTH ============
def setup_auth():
    """Setup authentication — tries 3 methods."""
    
    method_used = None
    
    # Method 1: Base64 encoded cookies (BEST)
    cookies_b64 = os.environ.get("YOUTUBE_COOKIES_B64", "")
    if cookies_b64:
        try:
            decoded = base64.b64decode(cookies_b64)
            with open(COOKIES_FILE, "wb") as f:
                f.write(decoded)
            print("🍪 Auth Method: Base64 Cookies ✅")
            # Verify file
            size = os.path.getsize(COOKIES_FILE)
            print(f"   Cookie file size: {size} bytes")
            with open(COOKIES_FILE, "r") as f:
                lines = f.readlines()
                cookie_count = len([l for l in lines if l.strip() and not l.startswith('#')])
                print(f"   Cookie entries: {cookie_count}")
            method_used = "cookies_b64"
            return method_used
        except Exception as e:
            print(f"   ⚠️ Base64 decode failed: {e}")

    # Method 2: Raw cookies (may have formatting issues)
    cookies_raw = os.environ.get("YOUTUBE_COOKIES", "")
    if cookies_raw:
        with open(COOKIES_FILE, "w") as f:
            f.write(cookies_raw)
        print("🍪 Auth Method: Raw Cookies")
        size = os.path.getsize(COOKIES_FILE)
        print(f"   Cookie file size: {size} bytes")
        method_used = "cookies_raw"
        return method_used

    # Method 3: yt-dlp OAuth token
    oauth_token = os.environ.get("YTDLP_OAUTH_TOKEN", "")
    if oauth_token:
        with open(OAUTH_FILE, "w") as f:
            f.write(oauth_token)
        print("🔑 Auth Method: yt-dlp OAuth Token ✅")
        method_used = "oauth"
        return method_used

    print("⚠️  No authentication method found!")
    print("   Add one of these GitHub secrets:")
    print("   - YOUTUBE_COOKIES_B64 (recommended)")
    print("   - YOUTUBE_COOKIES")
    print("   - YTDLP_OAUTH_TOKEN")
    return None


# ============ COMMON YT-DLP OPTIONS ============
def get_ytdlp_opts():
    """Build yt-dlp options with best auth method."""
    opts = {
        'ignoreerrors': True,
        'retries': 10,
        'fragment_retries': 10,
        'extractor_retries': 5,
        'socket_timeout': 30,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        },
    }

    # Add cookies if file exists and has content
    if os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 100:
        opts['cookiefile'] = COOKIES_FILE

    # Add OAuth if file exists
    if os.path.exists(OAUTH_FILE):
        # yt-dlp uses this automatically if placed in right location
        config_dir = os.path.expanduser("~/.config/yt-dlp")
        os.makedirs(config_dir, exist_ok=True)
        target = os.path.join(config_dir, "youtube-oauth2-token.json")
        if not os.path.exists(target):
            import shutil
            shutil.copy(OAUTH_FILE, target)
        opts['username'] = 'oauth2'
        opts['password'] = ''

    return opts


# ============ HISTORY ============
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            return set(l.strip() for l in f if l.strip())
    return set()


def save_history(vid):
    with open(HISTORY_FILE, "a") as f:
        f.write(vid + "\n")


# ============ GET CHANNEL BASE ============
def get_channel_base(url):
    import re
    base = re.sub(r'/(videos|shorts|streams|playlists|community|about|featured)/?$', '', url.strip().rstrip('/'))
    return base


# ============ GET ALL CONTENT ============
def get_all_content(url):
    base_url = get_channel_base(url)
    videos_url = base_url + "/videos"
    shorts_url = base_url + "/shorts"

    all_content = []
    seen_ids = set()

    print(f"\n📹 Scanning regular videos...")
    videos = fetch_playlist(videos_url)
    for v in videos:
        if v['id'] not in seen_ids:
            v['type'] = 'video'
            all_content.append(v)
            seen_ids.add(v['id'])
    print(f"   Found: {len(videos)} regular videos")

    print(f"\n🎬 Scanning shorts/reels...")
    shorts = fetch_playlist(shorts_url)
    for s in shorts:
        if s['id'] not in seen_ids:
            s['type'] = 'short'
            all_content.append(s)
            seen_ids.add(s['id'])
    print(f"   Found: {len(shorts)} shorts/reels")

    print(f"\n📊 Total content: {len(all_content)}")
    return all_content


def fetch_playlist(url):
    opts = get_ytdlp_opts()
    opts['quiet'] = True
    opts['extract_flat'] = True

    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=False)
            entries = info.get('entries', [])
            return [
                {
                    'id': e['id'],
                    'url': f"https://www.youtube.com/watch?v={e['id']}",
                    'title': e.get('title', 'Untitled'),
                }
                for e in entries if e and e.get('id')
            ]
    except Exception as ex:
        print(f"   ⚠️ Error: {ex}")
        return []


# ============ DOWNLOAD WITH FALLBACKS ============
def download(url, vid):
    os.makedirs("dl", exist_ok=True)

    # Strategy: try different combinations
    strategies = [
        {
            'name': 'Default + cookies',
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'extra': {},
        },
        {
            'name': 'Android client',
            'format': 'best[ext=mp4]/best',
            'extra': {
                'extractor_args': {'youtube': {'player_client': ['android']}},
            },
        },
        {
            'name': 'iOS client',
            'format': 'best',
            'extra': {
                'extractor_args': {'youtube': {'player_client': ['ios']}},
            },
        },
        {
            'name': 'TV embedded',
            'format': 'best',
            'extra': {
                'extractor_args': {'youtube': {'player_client': ['tv_embedded']}},
            },
        },
        {
            'name': 'Media connect',
            'format': 'best',
            'extra': {
                'extractor_args': {'youtube': {'player_client': ['mediaconnect']}},
            },
        },
    ]

    last_error = None

    for strategy in strategies:
        try:
            # Clean up any previous partial download
            for ext in ['mp4', 'webm', 'mkv', 'part', 'ytdl', 'f*']:
                p = f'dl/{vid}.{ext}'
                if os.path.exists(p):
                    os.remove(p)

            opts = get_ytdlp_opts()
            opts.update({
                'format': strategy['format'],
                'outtmpl': f'dl/{vid}.%(ext)s',
                'merge_output_format': 'mp4',
                'quiet': False,
                'no_warnings': False,
                'ignoreerrors': False,
            })
            opts.update(strategy.get('extra', {}))

            print(f"\n   🔄 Trying: {strategy['name']}...")

            with yt_dlp.YoutubeDL(opts) as y:
                info = y.extract_info(url, download=True)

                if info is None:
                    print(f"   ⚠️ No info returned")
                    continue

                # Find downloaded file
                file_path = None
                for ext in ['mp4', 'webm', 'mkv', 'flv', 'avi', '3gp']:
                    p = f'dl/{vid}.{ext}'
                    if os.path.exists(p):
                        file_path = p
                        break

                if not file_path:
                    print(f"   ⚠️ No file found after download")
                    continue

                # Convert to mp4 if needed
                if not file_path.endswith('.mp4'):
                    mp4_path = f'dl/{vid}.mp4'
                    print(f"   Converting to mp4...")
                    cmd = ['ffmpeg', '-y', '-i', file_path,
                           '-c:v', 'libx264', '-c:a', 'aac', mp4_path]
                    subprocess.run(cmd, capture_output=True)
                    if os.path.exists(mp4_path):
                        os.remove(file_path)
                        file_path = mp4_path

                duration = info.get('duration', 0) or 0
                width = info.get('width', 0) or 0
                height = info.get('height', 0) or 0

                # Get dimensions from ffprobe if missing
                if width == 0 or height == 0:
                    width, height, duration = get_video_info(file_path)

                is_short = (duration <= 60) or (height > width)

                print(f"   ✅ Download OK! ({os.path.getsize(file_path)/1024/1024:.1f} MB)")
                return {
                    'id': vid,
                    'title': info.get('title', 'Untitled'),
                    'desc': info.get('description', ''),
                    'tags': info.get('tags', []) or [],
                    'file': file_path,
                    'duration': duration,
                    'width': width,
                    'height': height,
                    'is_short': is_short,
                }

        except Exception as e:
            last_error = str(e)
            print(f"   ❌ Failed: {str(e)[:100]}")
            continue

    # LAST RESORT: yt-dlp command line
    print(f"\n   🔄 Trying: Command line (last resort)...")
    try:
        result = try_cli_download(url, vid)
        if result:
            return result
    except Exception as e:
        last_error = str(e)

    raise Exception(f"All download methods failed for {vid}: {last_error}")


def try_cli_download(url, vid):
    """Try downloading via yt-dlp command line."""
    # Clean up
    for ext in ['mp4', 'webm', 'mkv', 'part']:
        p = f'dl/{vid}.{ext}'
        if os.path.exists(p):
            os.remove(p)

    cmd = ['yt-dlp',
           '--format', 'best',
           '--output', f'dl/{vid}.%(ext)s',
           '--merge-output-format', 'mp4',
           '--no-check-certificates',
           '--retries', '5',
           '--user-agent', 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36',
           ]

    # Add cookies
    if os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 100:
        cmd.extend(['--cookies', COOKIES_FILE])

    # Add OAuth
    if os.path.exists(OAUTH_FILE):
        cmd.extend(['--username', 'oauth2', '--password', ''])

    # Try different clients
    for client in ['android', 'ios', 'tv_embedded', 'mediaconnect']:
        try:
            full_cmd = cmd + [
                '--extractor-args', f'youtube:player_client={client}',
                url
            ]
            print(f"   CLI with {client} client...")
            result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=300)

            # Find file
            file_path = None
            for ext in ['mp4', 'webm', 'mkv']:
                p = f'dl/{vid}.{ext}'
                if os.path.exists(p):
                    file_path = p
                    break

            if file_path:
                # Convert if needed
                if not file_path.endswith('.mp4'):
                    mp4_path = f'dl/{vid}.mp4'
                    subprocess.run(['ffmpeg', '-y', '-i', file_path,
                                   '-c:v', 'libx264', '-c:a', 'aac', mp4_path],
                                  capture_output=True)
                    if os.path.exists(mp4_path):
                        os.remove(file_path)
                        file_path = mp4_path

                if os.path.exists(file_path):
                    width, height, duration = get_video_info(file_path)
                    is_short = (duration <= 60) or (height > width)

                    print(f"   ✅ CLI download OK!")
                    return {
                        'id': vid,
                        'title': 'Untitled',
                        'desc': '',
                        'tags': [],
                        'file': file_path,
                        'duration': duration,
                        'width': width,
                        'height': height,
                        'is_short': is_short,
                    }

        except subprocess.TimeoutExpired:
            print(f"   Timeout with {client}")
        except Exception as e:
            print(f"   Error with {client}: {e}")

        # Clean partial
        for ext in ['mp4', 'webm', 'mkv', 'part']:
            p = f'dl/{vid}.{ext}'
            if os.path.exists(p):
                os.remove(p)

    return None


def get_video_info(file_path):
    """Get video dimensions and duration using ffprobe."""
    try:
        cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json',
               '-show_format', '-show_streams', file_path]
        r = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(r.stdout)

        duration = float(data.get('format', {}).get('duration', 0))
        width = 1920
        height = 1080
        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'video':
                width = int(stream.get('width', 1920))
                height = int(stream.get('height', 1080))
                break
        return width, height, duration
    except:
        return 1920, 1080, 0


# ============ DETECT TYPE ============
def detect_type(meta, original_type):
    if original_type == 'short':
        return 'short'
    if meta.get('is_short', False):
        return 'short'
    if meta.get('height', 0) > meta.get('width', 0):
        return 'short'
    return 'video'


# ============ MODIFY REGULAR VIDEO ============
def modify_regular_video(inp, out, speed):
    os.makedirs("out", exist_ok=True)
    vf = ",".join([
        f"setpts=PTS/{speed}",
        "hflip",
        "crop=iw*0.95:ih*0.95",
        "scale=1920:1080:force_original_aspect_ratio=decrease",
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
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
    cmd = ["ffmpeg", "-y", "-i", inp,
           "-filter:v", vf, "-filter:a", af,
           "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
           "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", out]

    print("🔧 Modifying regular video...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FFmpeg error: {r.stderr[-500:]}")
        raise Exception("FFmpeg failed")
    print("✅ Video modified")


# ============ MODIFY SHORT ============
def modify_short_video(inp, out, speed):
    os.makedirs("out", exist_ok=True)
    vf = ",".join([
        f"setpts=PTS/{speed}",
        "hflip",
        "crop=iw*0.95:ih*0.95",
        "scale=1080:1920:force_original_aspect_ratio=decrease",
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
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
    cmd = ["ffmpeg", "-y", "-i", inp,
           "-filter:v", vf, "-filter:a", af,
           "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
           "-c:a", "aac", "-b:a", "192k",
           "-t", "59", "-movflags", "+faststart", out]

    print("🔧 Modifying short/reel...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"FFmpeg error: {r.stderr[-500:]}")
        raise Exception("FFmpeg failed")
    print("✅ Short modified")


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
    media = MediaFileUpload(path, mimetype='video/mp4',
                            resumable=True, chunksize=10*1024*1024)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    print(f"📤 Uploading: {title}")
    resp = None
    retry = 0
    while resp is None:
        try:
            status, resp = req.next_chunk()
            if status:
                print(f"   {int(status.progress()*100)}%")
        except HttpError as e:
            if e.resp.status in [500, 502, 503, 504]:
                retry += 1
                if retry > 10: raise
                time.sleep(2 ** retry)
                continue
            raise
        except Exception:
            retry += 1
            if retry > 10: raise
            time.sleep(5)
            continue

    print(f"✅ Uploaded! → https://youtu.be/{resp['id']}")
    return resp['id']


# ============ MAIN ============
def main():
    print("=" * 60)
    print("🚀 YouTube Automation — VIDEOS + SHORTS/REELS")
    print("=" * 60)

    if not SOURCE_URL:
        print("❌ SOURCE_URL not set!")
        sys.exit(1)

    # Setup auth
    print("\n🔐 Setting up authentication...")
    auth_method = setup_auth()
    if not auth_method:
        print("⚠️  Continuing without auth (may fail)...")

    history = load_history()
    print(f"📜 Already uploaded: {len(history)} items")

    all_content = get_all_content(SOURCE_URL)
    if not all_content:
        print("❌ No content found")
        return

    pending = [v for v in all_content if v['id'] not in history]
    if not pending:
        print("🎉 ALL content uploaded!")
        return

    if ORDER == "oldest":
        pending.reverse()

    pending_v = len([p for p in pending if p.get('type') == 'video'])
    pending_s = len([p for p in pending if p.get('type') == 'short'])

    print(f"\n📊 Total: {len(all_content)} | Done: {len(history)} | "
          f"Remaining: {len(pending)} (📹{pending_v} + 🎬{pending_s})")

    batch = pending[:BATCH_SIZE]
    yt = get_youtube()

    ok = 0
    fail = 0
    ok_v = 0
    ok_s = 0

    for i, v in enumerate(batch):
        try:
            ct = "SHORT/REEL" if v.get('type') == 'short' else "VIDEO"
            print(f"\n{'='*60}")
            print(f"[{i+1}/{len(batch)}] [{ct}] {v['title']}")
            print(f"{'='*60}")

            meta = download(v['url'], v['id'])
            content_type = detect_type(meta, v.get('type', 'video'))

            out_file = f"out/{v['id']}_mod.mp4"
            if content_type == 'short':
                modify_short_video(meta['file'], out_file, SPEED)
            else:
                modify_regular_video(meta['file'], out_file, SPEED)

            new_title = modify_title(meta['title'])
            if content_type == 'short' and '#shorts' not in new_title.lower():
                new_title = (new_title[:91] + " #Shorts") if len(new_title) > 91 else (new_title + " #Shorts")

            new_desc = modify_description(meta['desc'], new_title)
            if content_type == 'short' and '#shorts' not in new_desc.lower():
                new_desc = "#Shorts\n\n" + new_desc

            new_tags = modify_tags(meta['tags'])
            if content_type == 'short':
                extra = ["shorts","reels","viral shorts","ytshorts"]
                new_tags = list(dict.fromkeys(new_tags + extra))[:30]

            print(f"📝 {meta['title']} → {new_title}")

            upload_video(yt, out_file, new_title, new_desc, new_tags, PRIVACY)
            save_history(v['id'])
            ok += 1
            if content_type == 'short': ok_s += 1
            else: ok_v += 1

            for f in [meta['file'], out_file]:
                if os.path.exists(f): os.remove(f)

            if i < len(batch) - 1:
                time.sleep(30)

        except Exception as e:
            print(f"❌ ERROR: {e}")
            fail += 1
            for ext in ['mp4','webm','mkv','part']:
                for prefix in ['dl/', 'out/']:
                    p = f"{prefix}{v['id']}.{ext}"
                    if os.path.exists(p): os.remove(p)
                    p2 = f"{prefix}{v['id']}_mod.{ext}"
                    if os.path.exists(p2): os.remove(p2)

    # Cleanup auth files
    for f in [COOKIES_FILE, OAUTH_FILE]:
        if os.path.exists(f): os.remove(f)

    rem = len(pending) - ok
    print(f"\n{'='*60}")
    print(f"✅ Uploaded: {ok} (📹{ok_v} + 🎬{ok_s}) | ❌ Failed: {fail} | ⏳ Remaining: {rem}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

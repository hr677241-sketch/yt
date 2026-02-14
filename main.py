import os
import sys
import json
import time
import subprocess
import requests
import base64
import re
import yt_dlp
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from title_modifier import modify_title
from description_modifier import modify_description, modify_tags


# ============ CONFIG ============
SOURCE_URL   = os.environ.get("SOURCE_URL", "")
SPEED        = float(os.environ.get("SPEED", "1.05"))
BATCH_SIZE   = int(os.environ.get("BATCH_SIZE", "3"))
PRIVACY      = os.environ.get("PRIVACY", "public")
HISTORY_FILE = "history.txt"
ORDER        = os.environ.get("ORDER", "oldest")
COOKIES_FILE = "cookies.txt"

# Piped API instances (free YouTube proxies)
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
    "https://pipedapi.in.projectsegfau.lt",
    "https://api.piped.projectsegfau.lt",
    "https://pipedapi.r4fo.com",
    "https://pipedapi.leptons.xyz",
]

# Invidious API instances (another free YouTube proxy)
INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://invidious.jing.rocks",
    "https://invidious.privacyredirect.com",
    "https://iv.melmac.space",
    "https://invidious.protokoll-11.de",
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
}


# ============ SETUP COOKIES ============
def setup_cookies():
    cookies_b64 = os.environ.get("YOUTUBE_COOKIES_B64", "")
    if cookies_b64:
        try:
            decoded = base64.b64decode(cookies_b64)
            with open(COOKIES_FILE, "wb") as f:
                f.write(decoded)
            print("🍪 Cookies loaded (base64)")
            return True
        except:
            pass

    cookies_raw = os.environ.get("YOUTUBE_COOKIES", "")
    if cookies_raw:
        with open(COOKIES_FILE, "w") as f:
            f.write(cookies_raw)
        print("🍪 Cookies loaded (raw)")
        return True

    print("⚠️  No cookies (will use proxy APIs)")
    return False


# ============ HISTORY ============
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            return set(l.strip() for l in f if l.strip())
    return set()


def save_history(vid):
    with open(HISTORY_FILE, "a") as f:
        f.write(vid + "\n")


# ============ GET CHANNEL VIDEOS ============
def get_channel_base(url):
    base = re.sub(r'/(videos|shorts|streams|playlists|community|about|featured)/?$', '', url.strip().rstrip('/'))
    return base


def get_all_content(url):
    """Get all videos + shorts using Piped/Invidious API (not blocked)."""
    base_url = get_channel_base(url)

    # Extract channel identifier
    channel_id = extract_channel_id(base_url)

    all_content = []
    seen_ids = set()

    # Method 1: Try Piped API
    print("\n🔍 Fetching channel content via Piped API...")
    piped_videos = get_videos_piped(channel_id)
    if piped_videos:
        for v in piped_videos:
            if v['id'] not in seen_ids:
                all_content.append(v)
                seen_ids.add(v['id'])
        print(f"   ✅ Found {len(piped_videos)} items via Piped")

    # Method 2: Try Invidious API
    if not all_content:
        print("   Piped failed. Trying Invidious API...")
        inv_videos = get_videos_invidious(channel_id)
        if inv_videos:
            for v in inv_videos:
                if v['id'] not in seen_ids:
                    all_content.append(v)
                    seen_ids.add(v['id'])
            print(f"   ✅ Found {len(inv_videos)} items via Invidious")

    # Method 3: Fallback to yt-dlp (might work for listing even if download fails)
    if not all_content:
        print("   APIs failed. Trying yt-dlp for listing...")
        all_content = get_videos_ytdlp(base_url)

    print(f"\n📊 Total content found: {len(all_content)}")
    return all_content


def extract_channel_id(url):
    """Extract channel ID or handle from URL."""
    # https://www.youtube.com/@ChannelName
    match = re.search(r'youtube\.com/@([^/\s?]+)', url)
    if match:
        return "@" + match.group(1)

    # https://www.youtube.com/channel/UCxxxxx
    match = re.search(r'youtube\.com/channel/([^/\s?]+)', url)
    if match:
        return match.group(1)

    # https://www.youtube.com/c/ChannelName
    match = re.search(r'youtube\.com/c/([^/\s?]+)', url)
    if match:
        return match.group(1)

    return url


def get_videos_piped(channel_id):
    """Get videos from Piped API."""
    videos = []

    for instance in PIPED_INSTANCES:
        try:
            # Handle @username vs channel ID
            if channel_id.startswith("@"):
                # Search for channel first
                search_url = f"{instance}/search?q={channel_id}&filter=channels"
                r = requests.get(search_url, headers=HEADERS, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    items = data.get('items', [])
                    if items:
                        ch_url = items[0].get('url', '')
                        channel_id_resolved = ch_url.replace('/channel/', '')
                    else:
                        continue
                else:
                    continue
            else:
                channel_id_resolved = channel_id

            # Get channel videos
            api_url = f"{instance}/channel/{channel_id_resolved}"
            r = requests.get(api_url, headers=HEADERS, timeout=15)

            if r.status_code != 200:
                continue

            data = r.json()
            related = data.get('relatedStreams', [])

            for item in related:
                vid_url = item.get('url', '')
                vid_id = vid_url.replace('/watch?v=', '')
                if vid_id:
                    duration = item.get('duration', 0)
                    is_short = item.get('isShort', False) or (duration > 0 and duration <= 60)

                    videos.append({
                        'id': vid_id,
                        'url': f"https://www.youtube.com/watch?v={vid_id}",
                        'title': item.get('title', 'Untitled'),
                        'type': 'short' if is_short else 'video',
                        'duration': duration,
                    })

            # Get next pages
            nextpage = data.get('nextpage')
            page_count = 0
            while nextpage and page_count < 20:
                try:
                    np_url = f"{instance}/nextpage/channel/{channel_id_resolved}?nextpage={requests.utils.quote(nextpage)}"
                    r = requests.get(np_url, headers=HEADERS, timeout=15)
                    if r.status_code != 200:
                        break
                    data = r.json()
                    for item in data.get('relatedStreams', []):
                        vid_url = item.get('url', '')
                        vid_id = vid_url.replace('/watch?v=', '')
                        if vid_id and vid_id not in [v['id'] for v in videos]:
                            duration = item.get('duration', 0)
                            is_short = item.get('isShort', False) or (duration > 0 and duration <= 60)
                            videos.append({
                                'id': vid_id,
                                'url': f"https://www.youtube.com/watch?v={vid_id}",
                                'title': item.get('title', 'Untitled'),
                                'type': 'short' if is_short else 'video',
                                'duration': duration,
                            })
                    nextpage = data.get('nextpage')
                    page_count += 1
                except:
                    break

            if videos:
                return videos

        except Exception as e:
            print(f"   ⚠️ {instance}: {str(e)[:50]}")
            continue

    return videos


def get_videos_invidious(channel_id):
    """Get videos from Invidious API."""
    videos = []

    for instance in INVIDIOUS_INSTANCES:
        try:
            if channel_id.startswith("@"):
                search_url = f"{instance}/api/v1/search?q={channel_id}&type=channel"
                r = requests.get(search_url, headers=HEADERS, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    if data:
                        channel_id_resolved = data[0].get('authorId', '')
                    else:
                        continue
                else:
                    continue
            else:
                channel_id_resolved = channel_id

            # Get videos
            for page in range(1, 15):
                api_url = f"{instance}/api/v1/channels/{channel_id_resolved}/videos?page={page}"
                r = requests.get(api_url, headers=HEADERS, timeout=15)

                if r.status_code != 200:
                    break

                data = r.json()
                if not data:
                    break

                for item in data:
                    vid_id = item.get('videoId', '')
                    if vid_id and vid_id not in [v['id'] for v in videos]:
                        duration = item.get('lengthSeconds', 0)
                        videos.append({
                            'id': vid_id,
                            'url': f"https://www.youtube.com/watch?v={vid_id}",
                            'title': item.get('title', 'Untitled'),
                            'type': 'short' if duration <= 60 else 'video',
                            'duration': duration,
                        })

            # Also get shorts
            for page in range(1, 15):
                api_url = f"{instance}/api/v1/channels/{channel_id_resolved}/shorts?page={page}"
                r = requests.get(api_url, headers=HEADERS, timeout=15)

                if r.status_code != 200:
                    break

                data = r.json()
                if not data:
                    break

                for item in data:
                    vid_id = item.get('videoId', '')
                    if vid_id and vid_id not in [v['id'] for v in videos]:
                        videos.append({
                            'id': vid_id,
                            'url': f"https://www.youtube.com/watch?v={vid_id}",
                            'title': item.get('title', 'Untitled'),
                            'type': 'short',
                            'duration': item.get('lengthSeconds', 0),
                        })

            if videos:
                return videos

        except Exception as e:
            print(f"   ⚠️ {instance}: {str(e)[:50]}")
            continue

    return videos


def get_videos_ytdlp(base_url):
    """Fallback: get video list via yt-dlp."""
    videos = []
    opts = {
        'quiet': True,
        'extract_flat': True,
        'ignoreerrors': True,
    }
    if os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE

    for page_url in [base_url + "/videos", base_url + "/shorts"]:
        try:
            vtype = 'short' if '/shorts' in page_url else 'video'
            with yt_dlp.YoutubeDL(opts) as y:
                info = y.extract_info(page_url, download=False)
                for e in info.get('entries', []):
                    if e and e.get('id'):
                        videos.append({
                            'id': e['id'],
                            'url': f"https://www.youtube.com/watch?v={e['id']}",
                            'title': e.get('title', 'Untitled'),
                            'type': vtype,
                        })
        except:
            pass

    return videos


# ============ DOWNLOAD VIDEO (PROXY METHODS) ============
def download(url, vid, content_type='video'):
    """Download video using proxy APIs — bypasses YouTube IP block."""
    os.makedirs("dl", exist_ok=True)
    file_path = f"dl/{vid}.mp4"

    # Clean previous
    for ext in ['mp4', 'webm', 'mkv', 'part', 'f251.webm', 'f140.m4a']:
        p = f'dl/{vid}.{ext}'
        if os.path.exists(p):
            os.remove(p)

    meta = {'id': vid, 'title': 'Untitled', 'desc': '', 'tags': [],
            'file': file_path, 'duration': 0, 'width': 1920,
            'height': 1080, 'is_short': content_type == 'short'}

    # Method 1: Download via Piped
    print("   🔄 Method 1: Piped proxy...")
    result = download_via_piped(vid, file_path)
    if result:
        meta.update(result)
        meta['file'] = file_path
        return meta

    # Method 2: Download via Invidious
    print("   🔄 Method 2: Invidious proxy...")
    result = download_via_invidious(vid, file_path)
    if result:
        meta.update(result)
        meta['file'] = file_path
        return meta

    # Method 3: Download via Cobalt
    print("   🔄 Method 3: Cobalt API...")
    result = download_via_cobalt(vid, file_path)
    if result:
        meta.update(result)
        meta['file'] = file_path
        return meta

    # Method 4: yt-dlp with cookies (might work sometimes)
    print("   🔄 Method 4: yt-dlp direct (last resort)...")
    result = download_via_ytdlp(url, vid, file_path)
    if result:
        meta.update(result)
        meta['file'] = file_path
        return meta

    raise Exception(f"All 4 download methods failed for {vid}")


def download_via_piped(vid, output_path):
    """Download video + audio from Piped and merge with FFmpeg."""
    for instance in PIPED_INSTANCES:
        try:
            api_url = f"{instance}/streams/{vid}"
            r = requests.get(api_url, headers=HEADERS, timeout=20)

            if r.status_code != 200:
                continue

            data = r.json()
            title = data.get('title', 'Untitled')
            desc = data.get('description', '')
            duration = data.get('duration', 0)

            # Get video streams
            video_streams = data.get('videoStreams', [])
            audio_streams = data.get('audioStreams', [])

            if not video_streams:
                continue

            # Pick best video (mp4 preferred, highest quality)
            best_video = None
            for s in sorted(video_streams, key=lambda x: x.get('height', 0) or 0, reverse=True):
                if s.get('videoOnly', False) is False and s.get('url'):
                    best_video = s
                    break

            # If only video-only streams, get separate audio
            if not best_video:
                for s in sorted(video_streams, key=lambda x: x.get('height', 0) or 0, reverse=True):
                    if s.get('url'):
                        best_video = s
                        break

            if not best_video:
                continue

            video_url = best_video['url']
            height = best_video.get('height', 1080) or 1080
            width = best_video.get('width', 1920) or 1920

            # Check if video-only (needs separate audio)
            needs_audio = best_video.get('videoOnly', False)

            if needs_audio and audio_streams:
                # Get best audio
                best_audio = None
                for s in sorted(audio_streams, key=lambda x: x.get('bitrate', 0) or 0, reverse=True):
                    if s.get('url'):
                        best_audio = s
                        break

                if best_audio:
                    # Download video and audio separately, then merge
                    video_tmp = f"dl/{vid}_v.tmp"
                    audio_tmp = f"dl/{vid}_a.tmp"

                    print(f"   Downloading video from {instance}...")
                    download_file(video_url, video_tmp)
                    print(f"   Downloading audio...")
                    download_file(best_audio['url'], audio_tmp)

                    # Merge
                    print(f"   Merging video + audio...")
                    cmd = ['ffmpeg', '-y', '-i', video_tmp, '-i', audio_tmp,
                           '-c:v', 'copy', '-c:a', 'aac', '-strict', 'experimental',
                           output_path]
                    subprocess.run(cmd, capture_output=True)

                    # Cleanup
                    for f in [video_tmp, audio_tmp]:
                        if os.path.exists(f):
                            os.remove(f)
                else:
                    # No audio available, download video only
                    print(f"   Downloading from {instance}...")
                    download_file(video_url, output_path)
            else:
                # Video has audio included
                print(f"   Downloading from {instance}...")
                download_file(video_url, output_path)

            if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                # Ensure mp4 format
                ensure_mp4(output_path)

                # Get actual dimensions
                w, h, dur = get_video_info(output_path)

                print(f"   ✅ Piped download OK! ({os.path.getsize(output_path)/1024/1024:.1f} MB)")
                return {
                    'title': title,
                    'desc': desc,
                    'tags': data.get('tags', []) or [],
                    'duration': dur or duration,
                    'width': w or width,
                    'height': h or height,
                    'is_short': (duration <= 60) or (h > w if h and w else height > width),
                }

        except Exception as e:
            print(f"   ⚠️ {instance}: {str(e)[:60]}")
            # Cleanup
            for f in [output_path, f"dl/{vid}_v.tmp", f"dl/{vid}_a.tmp"]:
                if os.path.exists(f):
                    os.remove(f)
            continue

    return None


def download_via_invidious(vid, output_path):
    """Download from Invidious API."""
    for instance in INVIDIOUS_INSTANCES:
        try:
            api_url = f"{instance}/api/v1/videos/{vid}"
            r = requests.get(api_url, headers=HEADERS, timeout=20)

            if r.status_code != 200:
                continue

            data = r.json()
            title = data.get('title', 'Untitled')
            desc = data.get('description', '')
            duration = data.get('lengthSeconds', 0)

            # Get adaptive formats (separate video + audio)
            adaptive = data.get('adaptiveFormats', [])
            format_streams = data.get('formatStreams', [])

            # Try combined format streams first
            for stream in sorted(format_streams, key=lambda x: int(x.get('resolution', '0p').replace('p', '') or 0), reverse=True):
                dl_url = stream.get('url', '')
                if dl_url:
                    print(f"   Downloading from {instance}...")
                    download_file(dl_url, output_path)
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                        ensure_mp4(output_path)
                        w, h, dur = get_video_info(output_path)
                        print(f"   ✅ Invidious download OK!")
                        return {
                            'title': title,
                            'desc': desc,
                            'tags': data.get('keywords', []) or [],
                            'duration': dur or duration,
                            'width': w,
                            'height': h,
                            'is_short': (duration <= 60) or (h > w),
                        }
                    if os.path.exists(output_path):
                        os.remove(output_path)

            # Try adaptive (separate video + audio)
            best_video_url = None
            best_audio_url = None

            for fmt in adaptive:
                if fmt.get('type', '').startswith('video/') and fmt.get('url'):
                    if not best_video_url:
                        best_video_url = fmt['url']
                elif fmt.get('type', '').startswith('audio/') and fmt.get('url'):
                    if not best_audio_url:
                        best_audio_url = fmt['url']

            if best_video_url:
                video_tmp = f"dl/{vid}_v.tmp"
                audio_tmp = f"dl/{vid}_a.tmp"

                download_file(best_video_url, video_tmp)

                if best_audio_url:
                    download_file(best_audio_url, audio_tmp)
                    cmd = ['ffmpeg', '-y', '-i', video_tmp, '-i', audio_tmp,
                           '-c:v', 'copy', '-c:a', 'aac', output_path]
                    subprocess.run(cmd, capture_output=True)
                else:
                    os.rename(video_tmp, output_path)

                for f in [video_tmp, audio_tmp]:
                    if os.path.exists(f):
                        os.remove(f)

                if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                    ensure_mp4(output_path)
                    w, h, dur = get_video_info(output_path)
                    print(f"   ✅ Invidious adaptive download OK!")
                    return {
                        'title': title,
                        'desc': desc,
                        'tags': data.get('keywords', []) or [],
                        'duration': dur or duration,
                        'width': w,
                        'height': h,
                        'is_short': (duration <= 60) or (h > w),
                    }

        except Exception as e:
            print(f"   ⚠️ {instance}: {str(e)[:60]}")
            for f in [output_path, f"dl/{vid}_v.tmp", f"dl/{vid}_a.tmp"]:
                if os.path.exists(f):
                    os.remove(f)
            continue

    return None


def download_via_cobalt(vid, output_path):
    """Download via Cobalt API."""
    cobalt_apis = [
        "https://api.cobalt.tools",
    ]

    for api_base in cobalt_apis:
        try:
            api_url = f"{api_base}/api/json"
            payload = {
                "url": f"https://www.youtube.com/watch?v={vid}",
                "vCodec": "h264",
                "vQuality": "720",
                "aFormat": "mp3",
                "isAudioOnly": False,
            }
            cobalt_headers = {
                **HEADERS,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            }

            r = requests.post(api_url, json=payload, headers=cobalt_headers, timeout=30)

            if r.status_code != 200:
                continue

            data = r.json()
            status = data.get('status', '')

            if status == 'stream' or status == 'redirect':
                dl_url = data.get('url', '')
                if dl_url:
                    print(f"   Downloading from Cobalt...")
                    download_file(dl_url, output_path)
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                        ensure_mp4(output_path)
                        w, h, dur = get_video_info(output_path)
                        print(f"   ✅ Cobalt download OK!")
                        return {
                            'title': 'Untitled',
                            'desc': '',
                            'tags': [],
                            'duration': dur,
                            'width': w,
                            'height': h,
                            'is_short': (dur <= 60) or (h > w),
                        }

            elif status == 'picker':
                # Multiple streams
                picker = data.get('picker', [])
                if picker:
                    dl_url = picker[0].get('url', '')
                    if dl_url:
                        download_file(dl_url, output_path)
                        if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                            ensure_mp4(output_path)
                            w, h, dur = get_video_info(output_path)
                            return {
                                'title': 'Untitled', 'desc': '', 'tags': [],
                                'duration': dur, 'width': w, 'height': h,
                                'is_short': (dur <= 60) or (h > w),
                            }

        except Exception as e:
            print(f"   ⚠️ Cobalt: {str(e)[:60]}")
            continue

    return None


def download_via_ytdlp(url, vid, output_path):
    """Last resort: yt-dlp direct."""
    try:
        opts = {
            'format': 'best',
            'outtmpl': f'dl/{vid}.%(ext)s',
            'merge_output_format': 'mp4',
            'quiet': False,
            'ignoreerrors': False,
            'retries': 5,
        }
        if os.path.exists(COOKIES_FILE):
            opts['cookiefile'] = COOKIES_FILE

        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=True)
            if info and os.path.exists(output_path):
                w, h, dur = get_video_info(output_path)
                return {
                    'title': info.get('title', 'Untitled'),
                    'desc': info.get('description', ''),
                    'tags': info.get('tags', []) or [],
                    'duration': dur,
                    'width': w,
                    'height': h,
                    'is_short': (dur <= 60) or (h > w),
                }
    except:
        pass

    return None


# ============ HELPER FUNCTIONS ============
def download_file(url, output_path):
    """Download a file from URL with progress."""
    r = requests.get(url, headers=HEADERS, stream=True, timeout=300)
    r.raise_for_status()

    total = int(r.headers.get('content-length', 0))
    downloaded = 0

    with open(output_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = int(downloaded / total * 100)
                    if pct % 25 == 0:
                        print(f"   Download: {pct}% ({downloaded/1024/1024:.1f}MB)")


def ensure_mp4(file_path):
    """Convert to mp4 if needed."""
    if not file_path.endswith('.mp4'):
        mp4_path = file_path.rsplit('.', 1)[0] + '.mp4'
        cmd = ['ffmpeg', '-y', '-i', file_path,
               '-c:v', 'libx264', '-c:a', 'aac', mp4_path]
        subprocess.run(cmd, capture_output=True)
        if os.path.exists(mp4_path):
            os.remove(file_path)
            os.rename(mp4_path, file_path)


def get_video_info(file_path):
    """Get dimensions and duration via ffprobe."""
    try:
        cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json',
               '-show_format', '-show_streams', file_path]
        r = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(r.stdout)

        duration = float(data.get('format', {}).get('duration', 0))
        width, height = 1920, 1080
        for s in data.get('streams', []):
            if s.get('codec_type') == 'video':
                width = int(s.get('width', 1920))
                height = int(s.get('height', 1080))
                break
        return width, height, duration
    except:
        return 1920, 1080, 0


# ============ MODIFY VIDEOS ============
def detect_type(meta, original_type):
    if original_type == 'short':
        return 'short'
    if meta.get('is_short', False):
        return 'short'
    if meta.get('height', 0) > meta.get('width', 0):
        return 'short'
    return 'video'


def modify_regular_video(inp, out, speed):
    os.makedirs("out", exist_ok=True)
    vf = ",".join([
        f"setpts=PTS/{speed}", "hflip",
        "crop=iw*0.95:ih*0.95",
        "scale=1920:1080:force_original_aspect_ratio=decrease",
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
        "eq=brightness=0.04:contrast=1.06:saturation=1.08",
        "colorbalance=rs=0.03:gs=-0.02:bs=0.04",
        "unsharp=5:5:0.8:5:5:0.4",
    ])
    af = ",".join([
        f"atempo={speed}", "asetrate=44100*1.02", "aresample=44100",
        "bass=g=3:f=110", "equalizer=f=1000:width_type=h:width=200:g=-2",
    ])
    cmd = ["ffmpeg", "-y", "-i", inp,
           "-filter:v", vf, "-filter:a", af,
           "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise Exception(f"FFmpeg failed: {r.stderr[-300:]}")
    print("✅ Video modified")


def modify_short_video(inp, out, speed):
    os.makedirs("out", exist_ok=True)
    vf = ",".join([
        f"setpts=PTS/{speed}", "hflip",
        "crop=iw*0.95:ih*0.95",
        "scale=1080:1920:force_original_aspect_ratio=decrease",
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
        "eq=brightness=0.04:contrast=1.06:saturation=1.08",
        "colorbalance=rs=0.03:gs=-0.02:bs=0.04",
        "unsharp=5:5:0.8:5:5:0.4",
    ])
    af = ",".join([
        f"atempo={speed}", "asetrate=44100*1.02", "aresample=44100",
        "bass=g=3:f=110", "equalizer=f=1000:width_type=h:width=200:g=-2",
    ])
    cmd = ["ffmpeg", "-y", "-i", inp,
           "-filter:v", vf, "-filter:a", af,
           "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
           "-c:a", "aac", "-b:a", "192k", "-t", "59",
           "-movflags", "+faststart", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise Exception(f"FFmpeg failed: {r.stderr[-300:]}")
    print("✅ Short modified")


# ============ UPLOAD ============
def get_youtube():
    token_str = os.environ.get("YOUTUBE_TOKEN", "")
    if not token_str:
        sys.exit("❌ YOUTUBE_TOKEN not set")
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
        'snippet': {'title': title[:100], 'description': desc[:5000],
                     'tags': tags[:30], 'categoryId': '22'},
        'status': {'privacyStatus': privacy, 'selfDeclaredMadeForKids': False}
    }
    media = MediaFileUpload(path, mimetype='video/mp4',
                            resumable=True, chunksize=10*1024*1024)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)

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
        except:
            retry += 1
            if retry > 10: raise
            time.sleep(5)
    print(f"✅ Uploaded → https://youtu.be/{resp['id']}")
    return resp['id']


# ============ MAIN ============
def main():
    print("=" * 60)
    print("🚀 YouTube Automation — Proxy Download Method")
    print("=" * 60)

    if not SOURCE_URL:
        sys.exit("❌ SOURCE_URL not set!")

    setup_cookies()

    history = load_history()
    print(f"📜 Already done: {len(history)}")

    all_content = get_all_content(SOURCE_URL)
    if not all_content:
        sys.exit("❌ No content found")

    pending = [v for v in all_content if v['id'] not in history]
    if not pending:
        print("🎉 ALL content uploaded!")
        return

    if ORDER == "oldest":
        pending.reverse()

    pv = len([p for p in pending if p.get('type') == 'video'])
    ps = len([p for p in pending if p.get('type') == 'short'])
    print(f"📊 Total: {len(all_content)} | Done: {len(history)} | Left: {len(pending)} (📹{pv} 🎬{ps})")

    batch = pending[:BATCH_SIZE]
    yt = get_youtube()
    ok = fail = ok_v = ok_s = 0

    for i, v in enumerate(batch):
        try:
            ct = v.get('type', 'video')
            print(f"\n{'='*60}")
            print(f"[{i+1}/{len(batch)}] [{'SHORT' if ct=='short' else 'VIDEO'}] {v['title']}")
            print(f"{'='*60}")

            # Download via proxy
            print("\n⬇️  Downloading via proxy APIs...")
            meta = download(v['url'], v['id'], ct)
            content_type = detect_type(meta, ct)
            print(f"   Size: {os.path.getsize(meta['file'])/1024/1024:.1f}MB | "
                  f"Duration: {meta['duration']:.0f}s | {meta['width']}x{meta['height']}")

            # Modify video
            out_file = f"out/{v['id']}_mod.mp4"
            if content_type == 'short':
                modify_short_video(meta['file'], out_file, SPEED)
            else:
                modify_regular_video(meta['file'], out_file, SPEED)

            # Modify metadata
            new_title = modify_title(meta['title'])
            if content_type == 'short' and '#shorts' not in new_title.lower():
                new_title = (new_title[:91] + " #Shorts")

            new_desc = modify_description(meta['desc'], new_title)
            if content_type == 'short' and '#shorts' not in new_desc.lower():
                new_desc = "#Shorts\n\n" + new_desc

            new_tags = modify_tags(meta['tags'])
            if content_type == 'short':
                new_tags = list(dict.fromkeys(new_tags + ["shorts", "reels", "ytshorts"]))[:30]

            print(f"📝 {meta['title'][:40]}... → {new_title[:40]}...")

            # Upload
            upload_video(yt, out_file, new_title, new_desc, new_tags, PRIVACY)
            save_history(v['id'])
            ok += 1
            if content_type == 'short': ok_s += 1
            else: ok_v += 1

            # Cleanup
            for f in [meta['file'], out_file]:
                if os.path.exists(f): os.remove(f)

            if i < len(batch) - 1:
                time.sleep(30)

        except Exception as e:
            print(f"❌ ERROR: {e}")
            fail += 1
            for ext in ['mp4', 'webm', 'mkv', 'part', 'tmp']:
                for prefix in ['dl/', 'out/']:
                    for p in [f"{prefix}{v['id']}.{ext}", f"{prefix}{v['id']}_mod.{ext}",
                              f"{prefix}{v['id']}_v.{ext}", f"{prefix}{v['id']}_a.{ext}"]:
                        if os.path.exists(p): os.remove(p)

    if os.path.exists(COOKIES_FILE): os.remove(COOKIES_FILE)

    rem = len(pending) - ok
    print(f"\n{'='*60}")
    print(f"✅ {ok} (📹{ok_v} 🎬{ok_s}) | ❌ {fail} | ⏳ {rem} remaining")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

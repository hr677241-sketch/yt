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

# Tor proxy
TOR_PROXY    = "socks5://127.0.0.1:9050"
TOR_PROXY_H  = "socks5h://127.0.0.1:9050"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}


# ============ TOR HELPERS ============
def check_tor():
    """Check if Tor proxy is working."""
    try:
        proxies = {'http': TOR_PROXY_H, 'https': TOR_PROXY_H}
        r = requests.get('https://httpbin.org/ip', proxies=proxies, timeout=15)
        if r.status_code == 200:
            ip = r.json().get('origin', 'unknown')
            print(f"🧅 Tor is working! IP: {ip}")
            return True
    except Exception as e:
        print(f"⚠️ Tor check failed: {e}")
    return False


def renew_tor_ip():
    """Get a new Tor exit node (new IP)."""
    try:
        subprocess.run(['sudo', 'killall', '-HUP', 'tor'], capture_output=True)
        time.sleep(5)
        print("🔄 Tor IP renewed")
    except:
        pass


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

    print("ℹ️  No cookies — using Tor only")
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


# ============ GET ALL CONTENT ============
def get_channel_base(url):
    base = re.sub(r'/(videos|shorts|streams|playlists|community|about|featured)/?$', '', url.strip().rstrip('/'))
    return base


def get_all_content(url):
    """Get all videos + shorts from channel."""
    base_url = get_channel_base(url)
    all_content = []
    seen_ids = set()

    # Try fetching via yt-dlp through Tor
    for page_type in ['videos', 'shorts']:
        page_url = f"{base_url}/{page_type}"
        vtype = 'short' if page_type == 'shorts' else 'video'
        
        print(f"\n{'📹' if vtype == 'video' else '🎬'} Scanning /{page_type}...")
        
        items = fetch_channel_page(page_url, vtype)
        for item in items:
            if item['id'] not in seen_ids:
                all_content.append(item)
                seen_ids.add(item['id'])
        
        print(f"   Found: {len(items)} {page_type}")

    # Also try Piped/Invidious APIs via Tor
    if not all_content:
        print("\n🔄 Trying proxy APIs via Tor...")
        channel_id = extract_channel_id(base_url)
        api_items = fetch_via_apis(channel_id)
        for item in api_items:
            if item['id'] not in seen_ids:
                all_content.append(item)
                seen_ids.add(item['id'])

    print(f"\n📊 Total content found: {len(all_content)}")
    return all_content


def fetch_channel_page(url, vtype):
    """Fetch channel page using yt-dlp through Tor."""
    opts = {
        'quiet': True,
        'extract_flat': True,
        'ignoreerrors': True,
        'proxy': TOR_PROXY,
    }
    if os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE

    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=False)
            entries = info.get('entries', []) if info else []
            return [
                {
                    'id': e['id'],
                    'url': f"https://www.youtube.com/watch?v={e['id']}",
                    'title': e.get('title', 'Untitled'),
                    'type': vtype,
                }
                for e in entries if e and e.get('id')
            ]
    except Exception as ex:
        print(f"   ⚠️ yt-dlp listing error: {str(ex)[:80]}")
        return []


def extract_channel_id(url):
    match = re.search(r'youtube\.com/@([^/\s?]+)', url)
    if match:
        return "@" + match.group(1)
    match = re.search(r'youtube\.com/channel/([^/\s?]+)', url)
    if match:
        return match.group(1)
    return url


def fetch_via_apis(channel_id):
    """Fetch from Piped/Invidious APIs routed through Tor."""
    videos = []
    proxies = {'http': TOR_PROXY_H, 'https': TOR_PROXY_H}

    # Dynamically get working Piped instances
    piped_instances = get_working_piped_instances()
    
    for instance in piped_instances[:5]:
        try:
            # Resolve channel
            if channel_id.startswith("@"):
                r = requests.get(
                    f"{instance}/search?q={channel_id}&filter=channels",
                    headers=HEADERS, proxies=proxies, timeout=15
                )
                if r.status_code != 200:
                    continue
                data = r.json()
                items = data.get('items', [])
                if not items:
                    continue
                ch_path = items[0].get('url', '')
                resolved_id = ch_path.replace('/channel/', '')
            else:
                resolved_id = channel_id

            # Get channel videos
            r = requests.get(
                f"{instance}/channel/{resolved_id}",
                headers=HEADERS, proxies=proxies, timeout=15
            )
            if r.status_code != 200:
                continue

            data = r.json()
            for item in data.get('relatedStreams', []):
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
                    })

            # Get more pages
            nextpage = data.get('nextpage')
            pages = 0
            while nextpage and pages < 15:
                try:
                    r = requests.get(
                        f"{instance}/nextpage/channel/{resolved_id}",
                        params={'nextpage': nextpage},
                        headers=HEADERS, proxies=proxies, timeout=15
                    )
                    if r.status_code != 200:
                        break
                    pdata = r.json()
                    for item in pdata.get('relatedStreams', []):
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
                            })
                    nextpage = pdata.get('nextpage')
                    pages += 1
                except:
                    break

            if videos:
                print(f"   ✅ Got {len(videos)} items from {instance}")
                return videos

        except Exception as e:
            continue

    return videos


def get_working_piped_instances():
    """Dynamically fetch working Piped API instances."""
    try:
        r = requests.get(
            'https://piped-instances.kavin.rocks/',
            headers=HEADERS, timeout=10
        )
        if r.status_code == 200:
            instances = r.json()
            api_urls = [i.get('api_url', '') for i in instances if i.get('api_url')]
            if api_urls:
                print(f"   Found {len(api_urls)} Piped instances")
                return api_urls
    except:
        pass

    # Fallback static list
    return [
        "https://pipedapi.kavin.rocks",
        "https://pipedapi.r4fo.com",
        "https://pipedapi.adminforge.de",
    ]


# ============ DOWNLOAD VIA TOR ============
def download(url, vid, content_type='video'):
    """Download video through Tor proxy."""
    os.makedirs("dl", exist_ok=True)
    file_path = f"dl/{vid}.mp4"

    # Clean old files
    for ext in ['mp4','webm','mkv','part','f251.webm','f140.m4a']:
        p = f'dl/{vid}.{ext}'
        if os.path.exists(p):
            os.remove(p)

    # Try multiple download methods
    methods = [
        ("yt-dlp via Tor", lambda: download_ytdlp_tor(url, vid, file_path)),
        ("yt-dlp via Tor (new IP)", lambda: download_ytdlp_tor_retry(url, vid, file_path)),
        ("Piped API via Tor", lambda: download_piped_tor(vid, file_path)),
        ("Invidious API via Tor", lambda: download_invidious_tor(vid, file_path)),
        ("yt-dlp direct", lambda: download_ytdlp_direct(url, vid, file_path)),
    ]

    for name, method in methods:
        try:
            print(f"   🔄 {name}...")
            result = method()
            if result and os.path.exists(file_path) and os.path.getsize(file_path) > 10000:
                w, h, dur = get_video_info(file_path)
                is_short = content_type == 'short' or (dur <= 60) or (h > w)
                result['width'] = w
                result['height'] = h
                result['duration'] = dur
                result['is_short'] = is_short
                result['file'] = file_path
                print(f"   ✅ Downloaded! ({os.path.getsize(file_path)/1024/1024:.1f} MB)")
                return result
        except Exception as e:
            print(f"   ❌ {name} failed: {str(e)[:80]}")
            # Clean failed files
            for ext in ['mp4','webm','mkv','part']:
                p = f'dl/{vid}.{ext}'
                if os.path.exists(p):
                    os.remove(p)
            continue

    raise Exception(f"All download methods failed for {vid}")


def download_ytdlp_tor(url, vid, output):
    """Download using yt-dlp routed through Tor."""
    opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'dl/{vid}.%(ext)s',
        'merge_output_format': 'mp4',
        'proxy': TOR_PROXY,
        'quiet': False,
        'ignoreerrors': False,
        'retries': 5,
        'socket_timeout': 60,
        'http_headers': HEADERS,
    }
    if os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE

    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=True)
        if info is None:
            raise Exception("No info returned")

        # Find the file
        found = find_downloaded_file(vid)
        if found and found != output:
            convert_to_mp4(found, output)

        if not os.path.exists(output):
            raise Exception("File not found after download")

        return {
            'id': vid,
            'title': info.get('title', 'Untitled'),
            'desc': info.get('description', ''),
            'tags': info.get('tags', []) or [],
        }


def download_ytdlp_tor_retry(url, vid, output):
    """Renew Tor IP and try again."""
    renew_tor_ip()
    time.sleep(3)
    return download_ytdlp_tor(url, vid, output)


def download_piped_tor(vid, output):
    """Download from Piped API through Tor."""
    proxies = {'http': TOR_PROXY_H, 'https': TOR_PROXY_H}
    instances = get_working_piped_instances()

    for instance in instances[:8]:
        try:
            r = requests.get(
                f"{instance}/streams/{vid}",
                headers=HEADERS, proxies=proxies, timeout=20
            )
            if r.status_code != 200:
                continue

            data = r.json()
            title = data.get('title', 'Untitled')
            desc = data.get('description', '')

            # Find best stream with audio included
            video_streams = data.get('videoStreams', [])
            audio_streams = data.get('audioStreams', [])

            # Try combined streams first (video + audio)
            combined = [s for s in video_streams if not s.get('videoOnly', True) and s.get('url')]
            if combined:
                best = sorted(combined, key=lambda x: x.get('height', 0) or 0, reverse=True)[0]
                download_file_tor(best['url'], output)
                if os.path.exists(output) and os.path.getsize(output) > 10000:
                    return {'id': vid, 'title': title, 'desc': desc, 'tags': data.get('tags', [])}

            # Try video-only + audio merge
            video_only = [s for s in video_streams if s.get('url')]
            audios = [s for s in audio_streams if s.get('url')]

            if video_only and audios:
                best_v = sorted(video_only, key=lambda x: x.get('height', 0) or 0, reverse=True)[0]
                best_a = sorted(audios, key=lambda x: x.get('bitrate', 0) or 0, reverse=True)[0]

                vtmp = f"dl/{vid}_v.tmp"
                atmp = f"dl/{vid}_a.tmp"

                download_file_tor(best_v['url'], vtmp)
                download_file_tor(best_a['url'], atmp)

                if os.path.exists(vtmp) and os.path.exists(atmp):
                    cmd = ['ffmpeg', '-y', '-i', vtmp, '-i', atmp,
                           '-c:v', 'copy', '-c:a', 'aac', output]
                    subprocess.run(cmd, capture_output=True)

                for f in [vtmp, atmp]:
                    if os.path.exists(f):
                        os.remove(f)

                if os.path.exists(output) and os.path.getsize(output) > 10000:
                    return {'id': vid, 'title': title, 'desc': desc, 'tags': data.get('tags', [])}

        except Exception as e:
            continue

    raise Exception("All Piped instances failed")


def download_invidious_tor(vid, output):
    """Download from Invidious through Tor."""
    proxies = {'http': TOR_PROXY_H, 'https': TOR_PROXY_H}

    # Get working Invidious instances dynamically
    instances = get_working_invidious_instances()

    for instance in instances[:8]:
        try:
            r = requests.get(
                f"{instance}/api/v1/videos/{vid}",
                headers=HEADERS, proxies=proxies, timeout=20
            )
            if r.status_code != 200:
                continue

            data = r.json()
            title = data.get('title', 'Untitled')
            desc = data.get('description', '')
            tags = data.get('keywords', [])

            # Try format streams (combined video+audio)
            for stream in data.get('formatStreams', []):
                dl_url = stream.get('url', '')
                if dl_url:
                    download_file_tor(dl_url, output)
                    if os.path.exists(output) and os.path.getsize(output) > 10000:
                        return {'id': vid, 'title': title, 'desc': desc, 'tags': tags}
                    if os.path.exists(output):
                        os.remove(output)

            # Try adaptive formats
            adaptive = data.get('adaptiveFormats', [])
            best_v = None
            best_a = None
            for fmt in adaptive:
                ftype = fmt.get('type', '')
                if ftype.startswith('video/') and not best_v and fmt.get('url'):
                    best_v = fmt
                elif ftype.startswith('audio/') and not best_a and fmt.get('url'):
                    best_a = fmt

            if best_v:
                vtmp = f"dl/{vid}_v.tmp"
                atmp = f"dl/{vid}_a.tmp"

                download_file_tor(best_v['url'], vtmp)
                if best_a:
                    download_file_tor(best_a['url'], atmp)
                    cmd = ['ffmpeg', '-y', '-i', vtmp, '-i', atmp,
                           '-c:v', 'copy', '-c:a', 'aac', output]
                    subprocess.run(cmd, capture_output=True)
                else:
                    os.rename(vtmp, output)

                for f in [vtmp, atmp]:
                    if os.path.exists(f):
                        os.remove(f)

                if os.path.exists(output) and os.path.getsize(output) > 10000:
                    return {'id': vid, 'title': title, 'desc': desc, 'tags': tags}

        except:
            continue

    raise Exception("All Invidious instances failed")


def download_ytdlp_direct(url, vid, output):
    """Last resort: yt-dlp without proxy."""
    opts = {
        'format': 'best',
        'outtmpl': f'dl/{vid}.%(ext)s',
        'merge_output_format': 'mp4',
        'quiet': False,
        'ignoreerrors': False,
    }
    if os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE

    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=True)
        if not info:
            raise Exception("Failed")

        found = find_downloaded_file(vid)
        if found and found != output:
            convert_to_mp4(found, output)

        if os.path.exists(output) and os.path.getsize(output) > 10000:
            return {
                'id': vid,
                'title': info.get('title', 'Untitled'),
                'desc': info.get('description', ''),
                'tags': info.get('tags', []) or [],
            }

    raise Exception("Direct download failed")


def get_working_invidious_instances():
    """Get working Invidious instances dynamically."""
    try:
        r = requests.get('https://api.invidious.io/instances.json', timeout=10)
        if r.status_code == 200:
            data = r.json()
            instances = []
            for item in data:
                if len(item) >= 2:
                    info = item[1]
                    if info.get('api') and info.get('type') == 'https':
                        uri = info.get('uri', '')
                        if uri:
                            instances.append(uri)
            if instances:
                print(f"   Found {len(instances)} Invidious instances")
                return instances[:10]
    except:
        pass

    return [
        "https://inv.nadeko.net",
        "https://invidious.nerdvpn.de",
        "https://invidious.jing.rocks",
    ]


# ============ HELPER FUNCTIONS ============
def download_file_tor(url, output_path):
    """Download file through Tor."""
    proxies = {'http': TOR_PROXY_H, 'https': TOR_PROXY_H}
    r = requests.get(url, headers=HEADERS, proxies=proxies,
                     stream=True, timeout=300)
    r.raise_for_status()

    total = int(r.headers.get('content-length', 0))
    downloaded = 0

    with open(output_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=1024*1024):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0 and downloaded % (5*1024*1024) == 0:
                    print(f"      {downloaded/1024/1024:.0f}/{total/1024/1024:.0f} MB")


def find_downloaded_file(vid):
    """Find the downloaded file regardless of extension."""
    for ext in ['mp4', 'webm', 'mkv', 'flv', 'avi', '3gp']:
        p = f'dl/{vid}.{ext}'
        if os.path.exists(p):
            return p
    return None


def convert_to_mp4(input_path, output_path):
    """Convert any video to mp4."""
    cmd = ['ffmpeg', '-y', '-i', input_path,
           '-c:v', 'libx264', '-c:a', 'aac', output_path]
    subprocess.run(cmd, capture_output=True)
    if os.path.exists(output_path) and os.path.exists(input_path):
        os.remove(input_path)


def get_video_info(file_path):
    """Get dimensions and duration via ffprobe."""
    try:
        cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json',
               '-show_format', '-show_streams', file_path]
        r = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(r.stdout)
        duration = float(data.get('format', {}).get('duration', 0))
        w, h = 1920, 1080
        for s in data.get('streams', []):
            if s.get('codec_type') == 'video':
                w = int(s.get('width', 1920))
                h = int(s.get('height', 1080))
                break
        return w, h, duration
    except:
        return 1920, 1080, 0


# ============ MODIFY ============
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
        f"setpts=PTS/{speed}", "hflip", "crop=iw*0.95:ih*0.95",
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
        raise Exception(f"FFmpeg: {r.stderr[-300:]}")
    print("✅ Video modified")


def modify_short_video(inp, out, speed):
    os.makedirs("out", exist_ok=True)
    vf = ",".join([
        f"setpts=PTS/{speed}", "hflip", "crop=iw*0.95:ih*0.95",
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
        raise Exception(f"FFmpeg: {r.stderr[-300:]}")
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
            if e.resp.status in [500,502,503,504]:
                retry += 1
                if retry > 10: raise
                time.sleep(2**retry)
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
    print("🚀 YouTube Automation — Tor Proxy Method")
    print("=" * 60)

    if not SOURCE_URL:
        sys.exit("❌ SOURCE_URL not set!")

    # Setup
    setup_cookies()
    tor_ok = check_tor()

    if not tor_ok:
        print("⚠️ Tor not available — trying without it")

    history = load_history()
    print(f"📜 Already done: {len(history)}")

    # Get all content
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
    print(f"\n📊 Total: {len(all_content)} | Done: {len(history)} | Left: {len(pending)} (📹{pv} 🎬{ps})")

    batch = pending[:BATCH_SIZE]
    yt = get_youtube()
    ok = fail = ok_v = ok_s = 0

    for i, v in enumerate(batch):
        try:
            ct = v.get('type', 'video')
            print(f"\n{'='*60}")
            print(f"[{i+1}/{len(batch)}] [{'🎬 SHORT' if ct=='short' else '📹 VIDEO'}] {v['title']}")
            print(f"ID: {v['id']}")
            print(f"{'='*60}")

            # Download
            print("\n⬇️  Downloading...")
            meta = download(v['url'], v['id'], ct)
            content_type = detect_type(meta, ct)

            # Modify
            print("\n⚡ Modifying...")
            out_file = f"out/{v['id']}_mod.mp4"
            if content_type == 'short':
                modify_short_video(meta['file'], out_file, SPEED)
            else:
                modify_regular_video(meta['file'], out_file, SPEED)

            # Modify metadata
            new_title = modify_title(meta.get('title', v['title']))
            if content_type == 'short' and '#shorts' not in new_title.lower():
                new_title = (new_title[:91] + " #Shorts") if len(new_title) > 91 else (new_title + " #Shorts")

            new_desc = modify_description(meta.get('desc', ''), new_title)
            if content_type == 'short' and '#shorts' not in new_desc.lower():
                new_desc = "#Shorts\n\n" + new_desc

            new_tags = modify_tags(meta.get('tags', []))
            if content_type == 'short':
                new_tags = list(dict.fromkeys(new_tags + ["shorts","reels","ytshorts"]))[:30]

            print(f"\n📝 {v['title'][:35]}... → {new_title[:35]}...")

            # Upload
            print("\n📤 Uploading...")
            upload_video(yt, out_file, new_title, new_desc, new_tags, PRIVACY)
            save_history(v['id'])
            ok += 1
            if content_type == 'short':
                ok_s += 1
            else:
                ok_v += 1

            # Cleanup
            for f in [meta['file'], out_file]:
                if os.path.exists(f):
                    os.remove(f)

            if i < len(batch) - 1:
                print("⏳ Waiting 30s + renewing Tor IP...")
                renew_tor_ip()
                time.sleep(30)

        except Exception as e:
            print(f"\n❌ ERROR: {e}")
            fail += 1
            for ext in ['mp4','webm','mkv','part','tmp']:
                for pre in ['dl/','out/']:
                    for suffix in ['', '_mod', '_v', '_a']:
                        p = f"{pre}{v['id']}{suffix}.{ext}"
                        if os.path.exists(p):
                            os.remove(p)
            # Renew Tor IP after failure
            renew_tor_ip()
            continue

    # Cleanup
    if os.path.exists(COOKIES_FILE):
        os.remove(COOKIES_FILE)

    rem = len(pending) - ok
    print(f"\n{'='*60}")
    print(f"✅ {ok} (📹{ok_v} 🎬{ok_s}) | ❌ {fail} | ⏳ {rem} remaining")
    if rem > 0:
        print(f"Next run: {min(BATCH_SIZE, rem)} more | ~{rem//BATCH_SIZE+1} runs left")
    else:
        print("🎉 ALL DONE!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

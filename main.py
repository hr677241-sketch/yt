import os
import sys
import json
import time
import subprocess
import requests
import base64
import re
import random
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

TOR_PROXY    = "socks5://127.0.0.1:9050"
TOR_PROXY_H  = "socks5h://127.0.0.1:9050"

# Max times to rotate Tor IP and retry per video
MAX_TOR_RETRIES = 15

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}


# ============ TOR ============
def check_tor():
    try:
        proxies = {'http': TOR_PROXY_H, 'https': TOR_PROXY_H}
        r = requests.get('https://httpbin.org/ip', proxies=proxies, timeout=15)
        if r.status_code == 200:
            ip = r.json().get('origin', '?')
            print(f"🧅 Tor working! IP: {ip}")
            return True
    except:
        pass
    return False


def renew_tor():
    """Get completely new Tor circuit (new IP)."""
    try:
        subprocess.run(['sudo', 'killall', '-HUP', 'tor'],
                       capture_output=True, timeout=10)
        time.sleep(8)
    except:
        try:
            subprocess.run(['sudo', 'service', 'tor', 'restart'],
                           capture_output=True, timeout=30)
            time.sleep(12)
        except:
            pass

    # Verify new IP
    try:
        proxies = {'http': TOR_PROXY_H, 'https': TOR_PROXY_H}
        r = requests.get('https://httpbin.org/ip', proxies=proxies, timeout=10)
        ip = r.json().get('origin', '?')
        print(f"   🔄 New Tor IP: {ip}")
    except:
        print("   🔄 Tor IP renewed (couldn't verify)")


def find_deno_path():
    """Find deno executable."""
    paths = [
        os.path.expanduser("~/.deno/bin/deno"),
        "/home/runner/.deno/bin/deno",
        "/usr/local/bin/deno",
        "/usr/bin/deno",
    ]
    for p in paths:
        if os.path.exists(p):
            return p

    # Try which
    try:
        r = subprocess.run(['which', 'deno'], capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout.strip()
    except:
        pass

    return None


# ============ COOKIES ============
def setup_cookies():
    cookies_b64 = os.environ.get("YOUTUBE_COOKIES_B64", "")
    if cookies_b64:
        try:
            decoded = base64.b64decode(cookies_b64)
            with open(COOKIES_FILE, "wb") as f:
                f.write(decoded)
            print("🍪 Cookies loaded")
            return True
        except:
            pass

    cookies_raw = os.environ.get("YOUTUBE_COOKIES", "")
    if cookies_raw:
        with open(COOKIES_FILE, "w") as f:
            f.write(cookies_raw)
        print("🍪 Cookies loaded")
        return True

    print("ℹ️  No cookies")
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


# ============ CHANNEL LISTING ============
def get_channel_base(url):
    return re.sub(r'/(videos|shorts|streams|playlists|community|about|featured)/?$',
                  '', url.strip().rstrip('/'))


def get_all_content(url):
    base_url = get_channel_base(url)
    all_content = []
    seen = set()

    for page_type in ['videos', 'shorts']:
        page_url = f"{base_url}/{page_type}"
        vtype = 'short' if page_type == 'shorts' else 'video'
        emoji = '🎬' if vtype == 'short' else '📹'
        print(f"\n{emoji} Scanning /{page_type}...")

        items = fetch_listing(page_url, vtype)
        for item in items:
            if item['id'] not in seen:
                all_content.append(item)
                seen.add(item['id'])
        print(f"   Found: {len(items)}")

    print(f"\n📊 Total: {len(all_content)}")
    return all_content


def fetch_listing(url, vtype):
    """Fetch video listing — uses Tor proxy."""
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
            if not info:
                return []
            return [
                {
                    'id': e['id'],
                    'url': f"https://www.youtube.com/watch?v={e['id']}",
                    'title': e.get('title', 'Untitled'),
                    'type': vtype,
                }
                for e in info.get('entries', []) if e and e.get('id')
            ]
    except Exception as e:
        print(f"   ⚠️ Listing error: {str(e)[:80]}")
        return []


# ============ DOWNLOAD — AGGRESSIVE TOR RETRY ============
def download(url, vid, content_type='video'):
    """
    Download video using aggressive Tor IP rotation.
    Tries up to MAX_TOR_RETRIES different Tor exit nodes.
    """
    os.makedirs("dl", exist_ok=True)
    file_path = f"dl/{vid}.mp4"

    # Find JS runtime
    deno = find_deno_path()
    js_runtime_args = []
    if deno:
        print(f"   JS runtime: deno ({deno})")
        js_runtime_args = ['--js-runtimes', f'deno:{deno}']
    else:
        print("   JS runtime: node (fallback)")
        js_runtime_args = ['--js-runtimes', 'node']

    # ── METHOD 1: torsocks + yt-dlp CLI (most reliable) ──
    for attempt in range(1, MAX_TOR_RETRIES + 1):
        print(f"\n   🔄 Attempt {attempt}/{MAX_TOR_RETRIES} — torsocks + yt-dlp CLI")

        # Clean old files
        clean_download_files(vid)

        try:
            cmd = [
                'torsocks', 'yt-dlp',
                '--format', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                '--output', f'dl/{vid}.%(ext)s',
                '--merge-output-format', 'mp4',
                '--retries', '3',
                '--socket-timeout', '30',
                '--user-agent', HEADERS['User-Agent'],
                '--no-check-certificates',
            ] + js_runtime_args

            if os.path.exists(COOKIES_FILE):
                cmd.extend(['--cookies', COOKIES_FILE])

            cmd.append(url)

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            # Check if file exists
            found = find_file(vid)
            if found:
                if not found.endswith('.mp4'):
                    convert_to_mp4(found, file_path)
                elif found != file_path:
                    os.rename(found, file_path)

                if os.path.exists(file_path) and os.path.getsize(file_path) > 10000:
                    # Get metadata from yt-dlp output
                    meta = extract_meta_from_output(result.stdout, vid)
                    w, h, dur = get_video_info(file_path)
                    meta.update({
                        'file': file_path,
                        'width': w, 'height': h, 'duration': dur,
                        'is_short': content_type == 'short' or (dur <= 60) or (h > w),
                    })
                    print(f"   ✅ Downloaded! ({os.path.getsize(file_path)/1024/1024:.1f} MB)")
                    return meta

            # Check error
            if 'Sign in to confirm' in result.stderr or 'bot' in result.stderr.lower():
                print(f"   ⚠️ Bot detection — rotating IP...")
                renew_tor()
                continue
            elif result.stderr:
                print(f"   ⚠️ Error: {result.stderr[-100:]}")
                renew_tor()
                continue

        except subprocess.TimeoutExpired:
            print(f"   ⚠️ Timeout — rotating IP...")
            renew_tor()
            continue
        except Exception as e:
            print(f"   ⚠️ {str(e)[:80]}")
            renew_tor()
            continue

    # ── METHOD 2: Python yt-dlp with proxy (backup) ──
    for attempt in range(1, 6):
        print(f"\n   🔄 Python yt-dlp attempt {attempt}/5")
        clean_download_files(vid)
        renew_tor()

        try:
            opts = {
                'format': 'best[ext=mp4]/best',
                'outtmpl': f'dl/{vid}.%(ext)s',
                'merge_output_format': 'mp4',
                'proxy': TOR_PROXY,
                'quiet': False,
                'ignoreerrors': False,
                'retries': 3,
                'socket_timeout': 30,
                'http_headers': HEADERS,
            }
            if os.path.exists(COOKIES_FILE):
                opts['cookiefile'] = COOKIES_FILE

            with yt_dlp.YoutubeDL(opts) as y:
                info = y.extract_info(url, download=True)

            if info:
                found = find_file(vid)
                if found:
                    if not found.endswith('.mp4'):
                        convert_to_mp4(found, file_path)
                    elif found != file_path:
                        os.rename(found, file_path)

                if os.path.exists(file_path) and os.path.getsize(file_path) > 10000:
                    w, h, dur = get_video_info(file_path)
                    print(f"   ✅ Downloaded via Python! ({os.path.getsize(file_path)/1024/1024:.1f} MB)")
                    return {
                        'id': vid,
                        'title': info.get('title', 'Untitled'),
                        'desc': info.get('description', ''),
                        'tags': info.get('tags', []) or [],
                        'file': file_path,
                        'width': w, 'height': h, 'duration': dur,
                        'is_short': content_type == 'short' or (dur <= 60) or (h > w),
                    }

        except Exception as e:
            if 'Sign in' in str(e) or 'bot' in str(e).lower():
                print(f"   ⚠️ Bot blocked — rotating...")
            else:
                print(f"   ⚠️ {str(e)[:80]}")
            continue

    # ── METHOD 3: Piped/Invidious APIs via Tor ──
    print(f"\n   🔄 Trying proxy APIs...")
    renew_tor()

    result = download_via_api(vid, file_path)
    if result:
        return result

    raise Exception(f"ALL methods failed after {MAX_TOR_RETRIES}+ attempts for {vid}")


def download_via_api(vid, output):
    """Try Piped and Invidious APIs through Tor."""
    proxies = {'http': TOR_PROXY_H, 'https': TOR_PROXY_H}

    # Get instances dynamically
    piped = get_piped_instances()
    invidious = get_invidious_instances()

    # Try Piped
    for inst in piped[:5]:
        try:
            r = requests.get(f"{inst}/streams/{vid}",
                           headers=HEADERS, proxies=proxies, timeout=20)
            if r.status_code != 200:
                continue

            data = r.json()
            title = data.get('title', 'Untitled')

            # Get combined stream (video + audio)
            streams = data.get('videoStreams', [])
            combined = [s for s in streams if not s.get('videoOnly', True) and s.get('url')]

            if combined:
                best = sorted(combined, key=lambda x: x.get('height', 0) or 0, reverse=True)[0]
                download_file_via_tor(best['url'], output)
                if os.path.exists(output) and os.path.getsize(output) > 10000:
                    w, h, dur = get_video_info(output)
                    return {
                        'id': vid, 'title': title,
                        'desc': data.get('description', ''),
                        'tags': data.get('tags', []) or [],
                        'file': output, 'width': w, 'height': h, 'duration': dur,
                        'is_short': (dur <= 60) or (h > w),
                    }

            # Try separate video + audio
            video_only = [s for s in streams if s.get('url')]
            audios = data.get('audioStreams', [])
            audios = [a for a in audios if a.get('url')]

            if video_only and audios:
                bv = sorted(video_only, key=lambda x: x.get('height', 0) or 0, reverse=True)[0]
                ba = sorted(audios, key=lambda x: x.get('bitrate', 0) or 0, reverse=True)[0]

                vtmp = f"dl/{vid}_v.tmp"
                atmp = f"dl/{vid}_a.tmp"
                download_file_via_tor(bv['url'], vtmp)
                download_file_via_tor(ba['url'], atmp)

                if os.path.exists(vtmp) and os.path.exists(atmp):
                    subprocess.run(['ffmpeg', '-y', '-i', vtmp, '-i', atmp,
                                   '-c:v', 'copy', '-c:a', 'aac', output],
                                  capture_output=True)

                for f in [vtmp, atmp]:
                    if os.path.exists(f): os.remove(f)

                if os.path.exists(output) and os.path.getsize(output) > 10000:
                    w, h, dur = get_video_info(output)
                    return {
                        'id': vid, 'title': title,
                        'desc': data.get('description', ''),
                        'tags': data.get('tags', []) or [],
                        'file': output, 'width': w, 'height': h, 'duration': dur,
                        'is_short': (dur <= 60) or (h > w),
                    }

        except:
            continue

    # Try Invidious
    for inst in invidious[:5]:
        try:
            r = requests.get(f"{inst}/api/v1/videos/{vid}",
                           headers=HEADERS, proxies=proxies, timeout=20)
            if r.status_code != 200:
                continue

            data = r.json()
            for stream in data.get('formatStreams', []):
                dl_url = stream.get('url', '')
                if dl_url:
                    download_file_via_tor(dl_url, output)
                    if os.path.exists(output) and os.path.getsize(output) > 10000:
                        w, h, dur = get_video_info(output)
                        return {
                            'id': vid,
                            'title': data.get('title', 'Untitled'),
                            'desc': data.get('description', ''),
                            'tags': data.get('keywords', []) or [],
                            'file': output, 'width': w, 'height': h, 'duration': dur,
                            'is_short': (dur <= 60) or (h > w),
                        }
                    if os.path.exists(output): os.remove(output)
        except:
            continue

    return None


def get_piped_instances():
    try:
        r = requests.get('https://piped-instances.kavin.rocks/', timeout=10)
        if r.status_code == 200:
            return [i['api_url'] for i in r.json() if i.get('api_url')]
    except:
        pass
    return ["https://pipedapi.kavin.rocks"]


def get_invidious_instances():
    try:
        r = requests.get('https://api.invidious.io/instances.json', timeout=10)
        if r.status_code == 200:
            return [i[1]['uri'] for i in r.json()
                    if len(i) >= 2 and i[1].get('api') and i[1].get('type') == 'https']
    except:
        pass
    return ["https://inv.nadeko.net"]


# ============ HELPERS ============
def download_file_via_tor(url, output):
    proxies = {'http': TOR_PROXY_H, 'https': TOR_PROXY_H}
    r = requests.get(url, headers=HEADERS, proxies=proxies, stream=True, timeout=300)
    r.raise_for_status()
    with open(output, 'wb') as f:
        for chunk in r.iter_content(chunk_size=1024*1024):
            if chunk:
                f.write(chunk)


def find_file(vid):
    for ext in ['mp4', 'webm', 'mkv', 'flv', 'avi', '3gp']:
        p = f'dl/{vid}.{ext}'
        if os.path.exists(p) and os.path.getsize(p) > 1000:
            return p
    return None


def clean_download_files(vid):
    for ext in ['mp4','webm','mkv','part','f251.webm','f140.m4a','flv','3gp']:
        p = f'dl/{vid}.{ext}'
        if os.path.exists(p):
            os.remove(p)
    for suffix in ['_v.tmp', '_a.tmp']:
        p = f'dl/{vid}{suffix}'
        if os.path.exists(p):
            os.remove(p)


def convert_to_mp4(inp, out):
    subprocess.run(['ffmpeg', '-y', '-i', inp,
                   '-c:v', 'libx264', '-c:a', 'aac', out],
                  capture_output=True)
    if os.path.exists(out) and os.path.exists(inp):
        os.remove(inp)


def get_video_info(path):
    try:
        cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json',
               '-show_format', '-show_streams', path]
        r = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(r.stdout)
        dur = float(data.get('format', {}).get('duration', 0))
        w, h = 1920, 1080
        for s in data.get('streams', []):
            if s.get('codec_type') == 'video':
                w = int(s.get('width', 1920))
                h = int(s.get('height', 1080))
                break
        return w, h, dur
    except:
        return 1920, 1080, 0


def extract_meta_from_output(stdout, vid):
    """Extract title from yt-dlp stdout if possible."""
    meta = {'id': vid, 'title': 'Untitled', 'desc': '', 'tags': []}
    if stdout:
        for line in stdout.split('\n'):
            if 'Destination:' in line:
                # Try to get title from filename
                pass
    return meta


# ============ MODIFY ============
def detect_type(meta, original_type):
    if original_type == 'short': return 'short'
    if meta.get('is_short', False): return 'short'
    if meta.get('height', 0) > meta.get('width', 0): return 'short'
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
    cmd = ["ffmpeg", "-y", "-i", inp, "-filter:v", vf, "-filter:a", af,
           "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise Exception(f"FFmpeg: {r.stderr[-200:]}")
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
    cmd = ["ffmpeg", "-y", "-i", inp, "-filter:v", vf, "-filter:a", af,
           "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
           "-c:a", "aac", "-b:a", "192k", "-t", "59",
           "-movflags", "+faststart", out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise Exception(f"FFmpeg: {r.stderr[-200:]}")
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
    print("🚀 YouTube Automation — Tor + Aggressive Retry")
    print("=" * 60)

    if not SOURCE_URL:
        sys.exit("❌ SOURCE_URL not set!")

    setup_cookies()
    tor_ok = check_tor()
    if not tor_ok:
        print("⚠️  Tor not working! Trying to restart...")
        subprocess.run(['sudo', 'service', 'tor', 'restart'], capture_output=True)
        time.sleep(15)
        tor_ok = check_tor()
        if not tor_ok:
            print("❌ Tor failed to start. Downloads will likely fail.")

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
    print(f"\n📊 Total: {len(all_content)} | Done: {len(history)} | "
          f"Left: {len(pending)} (📹{pv} 🎬{ps})")

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

            # Download with aggressive retry
            print("\n⬇️  Downloading (up to 15 Tor IP rotations)...")
            meta = download(v['url'], v['id'], ct)
            content_type = detect_type(meta, ct)

            # Modify
            print("\n⚡ Modifying...")
            out_file = f"out/{v['id']}_mod.mp4"
            if content_type == 'short':
                modify_short_video(meta['file'], out_file, SPEED)
            else:
                modify_regular_video(meta['file'], out_file, SPEED)

            # Metadata
            new_title = modify_title(meta.get('title', v.get('title', 'Untitled')))
            if content_type == 'short' and '#shorts' not in new_title.lower():
                new_title = (new_title[:91] + " #Shorts") if len(new_title) > 91 else (new_title + " #Shorts")

            new_desc = modify_description(meta.get('desc', ''), new_title)
            if content_type == 'short' and '#shorts' not in new_desc.lower():
                new_desc = "#Shorts\n\n" + new_desc

            new_tags = modify_tags(meta.get('tags', []))
            if content_type == 'short':
                new_tags = list(dict.fromkeys(new_tags + ["shorts","reels","ytshorts"]))[:30]

            print(f"\n📝 {v['title'][:30]}... → {new_title[:30]}...")

            # Upload
            print("\n📤 Uploading...")
            upload_video(yt, out_file, new_title, new_desc, new_tags, PRIVACY)
            save_history(v['id'])
            ok += 1
            if content_type == 'short': ok_s += 1
            else: ok_v += 1

            # Cleanup
            for f in [meta['file'], out_file]:
                if os.path.exists(f): os.remove(f)

            if i < len(batch) - 1:
                print("\n⏳ Waiting 30s + new Tor IP...")
                renew_tor()
                time.sleep(30)

        except Exception as e:
            print(f"\n❌ FAILED: {e}")
            fail += 1
            clean_download_files(v['id'])
            for ext in ['mp4']:
                p = f"out/{v['id']}_mod.{ext}"
                if os.path.exists(p): os.remove(p)
            renew_tor()
            continue

    if os.path.exists(COOKIES_FILE): os.remove(COOKIES_FILE)

    rem = len(pending) - ok
    print(f"\n{'='*60}")
    print(f"✅ {ok} (📹{ok_v} 🎬{ok_s}) | ❌ {fail} | ⏳ {rem} left")
    if rem > 0 and ok > 0:
        print(f"Next run: ~{rem//BATCH_SIZE+1} more runs needed")
    elif ok == 0:
        print("⚠️  All failed. Try re-exporting cookies or wait and retry.")
    else:
        print("🎉 ALL DONE!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

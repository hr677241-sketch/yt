import os
import sys
import json
import time
import subprocess
import base64
import re
import yt_dlp
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from title_modifier import modify_title
from description_modifier import modify_description, modify_tags


# ====================== CONFIG ======================
SOURCE_URL   = os.environ.get("SOURCE_URL", "")
SPEED        = float(os.environ.get("SPEED", "1.05"))
BATCH_SIZE   = int(os.environ.get("BATCH_SIZE", "3"))
PRIVACY      = os.environ.get("PRIVACY", "public")
HISTORY_FILE = "history.txt"
ORDER        = os.environ.get("ORDER", "oldest")
COOKIES_FILE = "cookies.txt"
TOR_PROXY    = "socks5://127.0.0.1:9050"


# ====================== COOKIES ======================
def setup_cookies():
    """Load cookies from GitHub secret."""
    b64 = os.environ.get("YOUTUBE_COOKIES_B64", "")
    if b64:
        try:
            with open(COOKIES_FILE, "wb") as f:
                f.write(base64.b64decode(b64))
            print("🍪 Cookies loaded")
            return True
        except Exception as e:
            print(f"⚠️ Cookie decode error: {e}")
    return False


# ====================== HISTORY ======================
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            return set(l.strip() for l in f if l.strip())
    return set()


def save_history(vid):
    with open(HISTORY_FILE, "a") as f:
        f.write(vid + "\n")


# ====================== TOR HELPERS ======================
def renew_tor():
    """Get new Tor exit IP."""
    try:
        subprocess.run(["sudo", "killall", "-HUP", "tor"],
                       capture_output=True, timeout=10)
        time.sleep(8)
    except:
        try:
            subprocess.run(["sudo", "service", "tor", "restart"],
                           capture_output=True, timeout=30)
            time.sleep(12)
        except:
            pass


def find_deno():
    """Find deno path for yt-dlp JS runtime."""
    for p in [os.path.expanduser("~/.deno/bin/deno"),
              "/home/runner/.deno/bin/deno", "/usr/local/bin/deno"]:
        if os.path.exists(p):
            return p
    try:
        r = subprocess.run(["which", "deno"], capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout.strip()
    except:
        pass
    return None


# ====================== CHANNEL LISTING ======================
def get_channel_base(url):
    return re.sub(
        r'/(videos|shorts|streams|playlists|community|about|featured)/?$',
        '', url.strip().rstrip('/')
    )


def get_all_content(url):
    """Fetch ALL videos + shorts from channel."""
    base = get_channel_base(url)
    all_items = []
    seen = set()

    for page_type in ["videos", "shorts"]:
        page_url = f"{base}/{page_type}"
        vtype = "short" if page_type == "shorts" else "video"
        emoji = "🎬" if vtype == "short" else "📹"
        print(f"\n{emoji} Scanning /{page_type}...")

        items = _fetch_listing(page_url)
        count = 0
        for e in items:
            if e['id'] not in seen:
                e['type'] = vtype
                all_items.append(e)
                seen.add(e['id'])
                count += 1
        print(f"   Found: {count}")

    print(f"\n📊 Total content: {len(all_items)}")
    return all_items


def _fetch_listing(url):
    """List videos from channel page (listing is rarely blocked)."""
    opts = {'quiet': True, 'extract_flat': True, 'ignoreerrors': True}

    # Try with Tor first for listing
    for use_tor in [True, False]:
        try:
            if use_tor:
                opts['proxy'] = TOR_PROXY
            with yt_dlp.YoutubeDL(opts) as y:
                info = y.extract_info(url, download=False)
                if info and info.get('entries'):
                    return [
                        {'id': e['id'],
                         'url': f"https://www.youtube.com/watch?v={e['id']}",
                         'title': e.get('title', 'Untitled')}
                        for e in info['entries'] if e and e.get('id')
                    ]
        except:
            pass

    return []


# ====================== DOWNLOAD ======================
def download(url, vid, content_type="video"):
    """
    Download video with 4 strategies in order of speed:
    1. iOS client direct (fastest)
    2. Android client direct
    3. torsocks CLI (reliable)
    4. torsocks CLI with IP rotation (most robust)
    """
    os.makedirs("dl", exist_ok=True)
    file_path = f"dl/{vid}.mp4"
    _clean_files(vid)

    # Build strategies
    strategies = [
        ("iOS direct",    _download_ios,     {}),
        ("Android direct",_download_android, {}),
        ("Tor CLI",       _download_tor_cli, {"retries": 1}),
        ("Tor CLI retry", _download_tor_cli, {"retries": 8}),
    ]

    for name, func, kwargs in strategies:
        try:
            print(f"   🔄 {name}...")
            meta = func(url, vid, file_path, **kwargs)
            if meta and os.path.exists(file_path) and os.path.getsize(file_path) > 10000:
                w, h, dur = _get_info(file_path)
                meta.update({
                    'file': file_path, 'width': w, 'height': h,
                    'duration': dur,
                    'is_short': content_type == 'short' or dur <= 60 or h > w,
                })
                size = os.path.getsize(file_path) / 1024 / 1024
                print(f"   ✅ OK! {size:.1f}MB | {w}x{h} | {dur:.0f}s")
                return meta
        except Exception as e:
            msg = str(e)[:80]
            print(f"   ❌ {name}: {msg}")
            _clean_files(vid)
            continue

    raise Exception(f"All download methods failed for {vid}")


def _base_opts(vid):
    """Common yt-dlp options."""
    opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'dl/{vid}.%(ext)s',
        'merge_output_format': 'mp4',
        'quiet': False,
        'ignoreerrors': False,
        'retries': 3,
        'socket_timeout': 30,
    }
    if os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE
    return opts


def _download_ios(url, vid, output):
    """Strategy 1: iOS client impersonation."""
    opts = _base_opts(vid)
    opts['extractor_args'] = {
        'youtube': {
            'player_client': ['ios'],
            'player_skip': ['webpage', 'configs'],
        }
    }
    opts['http_headers'] = {
        'User-Agent': 'com.google.ios.youtube/19.29.1 (iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X;)',
    }
    return _run_ytdlp(url, vid, output, opts)


def _download_android(url, vid, output):
    """Strategy 2: Android client impersonation."""
    opts = _base_opts(vid)
    opts['extractor_args'] = {
        'youtube': {
            'player_client': ['android'],
            'player_skip': ['webpage', 'configs'],
        }
    }
    opts['http_headers'] = {
        'User-Agent': 'com.google.android.youtube/19.29.37 (Linux; U; Android 14; en_US) gzip',
    }
    return _run_ytdlp(url, vid, output, opts)


def _download_tor_cli(url, vid, output, retries=1):
    """Strategy 3/4: Download via torsocks command line."""
    deno = find_deno()

    for attempt in range(1, retries + 1):
        _clean_files(vid)

        if retries > 1:
            print(f"      Tor attempt {attempt}/{retries}")

        cmd = [
            "torsocks", "yt-dlp",
            "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--output", f"dl/{vid}.%(ext)s",
            "--merge-output-format", "mp4",
            "--retries", "3",
            "--socket-timeout", "30",
            "--no-check-certificates",
        ]

        if deno:
            cmd.extend(["--js-runtimes", f"deno:{deno}"])

        if os.path.exists(COOKIES_FILE):
            cmd.extend(["--cookies", COOKIES_FILE])

        cmd.append(url)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            # Find downloaded file
            found = _find_file(vid)
            if found:
                if found != output:
                    if not found.endswith('.mp4'):
                        _to_mp4(found, output)
                    else:
                        os.rename(found, output)

                if os.path.exists(output) and os.path.getsize(output) > 10000:
                    return {
                        'id': vid,
                        'title': _extract_title(result.stdout, vid),
                        'desc': '', 'tags': [],
                    }

            # Bot blocked — rotate IP
            if "Sign in" in result.stderr or "bot" in result.stderr.lower():
                if attempt < retries:
                    renew_tor()
                continue

        except subprocess.TimeoutExpired:
            if attempt < retries:
                renew_tor()
            continue

    raise Exception("Tor CLI failed")


def _run_ytdlp(url, vid, output, opts):
    """Execute yt-dlp Python download."""
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=True)

    if not info:
        raise Exception("No info returned")

    # Find the file
    found = _find_file(vid)
    if found and found != output:
        if not found.endswith('.mp4'):
            _to_mp4(found, output)
        else:
            os.rename(found, output)

    if not os.path.exists(output) or os.path.getsize(output) < 10000:
        raise Exception("File missing or too small")

    return {
        'id': vid,
        'title': info.get('title', 'Untitled'),
        'desc': info.get('description', ''),
        'tags': info.get('tags', []) or [],
    }


# ====================== HELPERS ======================
def _find_file(vid):
    for ext in ['mp4', 'webm', 'mkv', 'flv', 'avi']:
        p = f'dl/{vid}.{ext}'
        if os.path.exists(p) and os.path.getsize(p) > 1000:
            return p
    return None


def _clean_files(vid):
    for ext in ['mp4', 'webm', 'mkv', 'part', 'f251.webm', 'f140.m4a',
                'flv', 'avi', '_v.tmp', '_a.tmp']:
        p = f'dl/{vid}.{ext}'
        if os.path.exists(p):
            os.remove(p)
    for suffix in ['_v.tmp', '_a.tmp']:
        p = f'dl/{vid}{suffix}'
        if os.path.exists(p):
            os.remove(p)


def _to_mp4(inp, out):
    subprocess.run(['ffmpeg', '-y', '-i', inp,
                    '-c:v', 'libx264', '-c:a', 'aac', out],
                   capture_output=True)
    if os.path.exists(out) and os.path.exists(inp):
        os.remove(inp)


def _get_info(path):
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


def _extract_title(stdout, vid):
    if not stdout:
        return "Untitled"
    for line in stdout.split('\n'):
        if 'Destination:' in line:
            parts = line.split('Destination:')
            if len(parts) > 1:
                name = parts[1].strip()
                name = re.sub(r'\.[a-z0-9]+$', '', name)
                name = name.replace(vid, '').strip(' ._-')
                if name:
                    return name
    return "Untitled"


# ====================== VIDEO MODIFICATION ======================
def detect_type(meta, original_type):
    if original_type == 'short':
        return 'short'
    if meta.get('is_short', False):
        return 'short'
    if meta.get('height', 0) > meta.get('width', 0):
        return 'short'
    return 'video'


def modify_video(inp, out, speed, is_short=False):
    """Apply all anti-copyright modifications."""
    os.makedirs("out", exist_ok=True)

    if is_short:
        scale = "scale=1080:1920:force_original_aspect_ratio=decrease"
        pad = "pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
    else:
        scale = "scale=1920:1080:force_original_aspect_ratio=decrease"
        pad = "pad=1920:1080:(ow-iw)/2:(oh-ih)/2"

    vf = ",".join([
        f"setpts=PTS/{speed}",          # Speed up
        "hflip",                         # Mirror
        "crop=iw*0.95:ih*0.95",          # Crop 5%
        scale, pad,                      # Resize
        "eq=brightness=0.04:contrast=1.06:saturation=1.08",  # Color shift
        "colorbalance=rs=0.03:gs=-0.02:bs=0.04",             # Color tint
        "unsharp=5:5:0.8:5:5:0.4",      # Sharpen
    ])

    af = ",".join([
        f"atempo={speed}",              # Speed up audio
        "asetrate=44100*1.02",           # Pitch shift 2%
        "aresample=44100",               # Resample
        "bass=g=3:f=110",               # Bass boost
        "equalizer=f=1000:width_type=h:width=200:g=-2",  # EQ change
    ])

    cmd = [
        "ffmpeg", "-y", "-i", inp,
        "-filter:v", vf,
        "-filter:a", af,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
    ]

    if is_short:
        cmd.extend(["-t", "59"])         # Max 59s for shorts

    cmd.append(out)

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise Exception(f"FFmpeg failed: {r.stderr[-200:]}")

    print(f"   ✅ {'Short' if is_short else 'Video'} modified")


# ====================== UPLOAD ======================
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
                            resumable=True, chunksize=10 * 1024 * 1024)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    print(f"   📤 Uploading: {title[:50]}...")
    resp = None
    retry = 0
    while resp is None:
        try:
            status, resp = req.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                if pct % 25 == 0:
                    print(f"      {pct}%")
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

    vid_id = resp['id']
    print(f"   ✅ https://youtu.be/{vid_id}")
    return vid_id


# ====================== MAIN ======================
def main():
    print("=" * 60)
    print("🚀 YouTube Auto Pipeline — Final Version")
    print("=" * 60)

    if not SOURCE_URL:
        sys.exit("❌ SOURCE_URL not set!")

    # Setup
    has_cookies = setup_cookies()
    history = load_history()
    print(f"📜 Already uploaded: {len(history)}")

    # Get all content
    all_content = get_all_content(SOURCE_URL)
    if not all_content:
        sys.exit("❌ No content found on channel")

    # Filter pending
    pending = [v for v in all_content if v['id'] not in history]
    if not pending:
        print("🎉 ALL content already uploaded!")
        return

    if ORDER == "oldest":
        pending.reverse()

    pv = len([p for p in pending if p.get('type') == 'video'])
    ps = len([p for p in pending if p.get('type') == 'short'])

    print(f"\n📊 Channel: {len(all_content)} total | {len(history)} done | "
          f"{len(pending)} left (📹{pv} 🎬{ps})")
    print(f"📦 This batch: {min(BATCH_SIZE, len(pending))}")

    # Process batch
    batch = pending[:BATCH_SIZE]
    yt = get_youtube()
    ok = fail = ok_v = ok_s = 0

    for i, v in enumerate(batch):
        ct = v.get('type', 'video')
        emoji = "🎬" if ct == 'short' else "📹"

        print(f"\n{'=' * 60}")
        print(f"{emoji} [{i + 1}/{len(batch)}] {v['title']}")
        print(f"   ID: {v['id']} | Type: {ct.upper()}")
        print(f"{'=' * 60}")

        try:
            # ── DOWNLOAD ──
            print("\n⬇️  Downloading...")
            meta = download(v['url'], v['id'], ct)
            content_type = detect_type(meta, ct)

            # ── MODIFY VIDEO ──
            print("\n⚡ Modifying video...")
            out_file = f"out/{v['id']}_mod.mp4"
            is_short = content_type == 'short'
            modify_video(meta['file'], out_file, SPEED, is_short)

            # ── MODIFY TITLE ──
            original_title = meta.get('title') or v.get('title') or 'Untitled'
            new_title = modify_title(original_title)
            if is_short and '#shorts' not in new_title.lower():
                if len(new_title) > 91:
                    new_title = new_title[:91] + " #Shorts"
                else:
                    new_title = new_title + " #Shorts"

            print(f"\n📝 Title:")
            print(f"   OLD: {original_title[:50]}")
            print(f"   NEW: {new_title[:50]}")

            # ── MODIFY DESCRIPTION ──
            new_desc = modify_description(meta.get('desc', ''), new_title)
            if is_short and '#shorts' not in new_desc.lower():
                new_desc = "#Shorts\n\n" + new_desc

            # ── MODIFY TAGS ──
            new_tags = modify_tags(meta.get('tags', []))
            if is_short:
                new_tags = list(dict.fromkeys(
                    new_tags + ["shorts", "reels", "ytshorts", "short video"]
                ))[:30]

            # ── UPLOAD ──
            print("\n📤 Uploading...")
            upload_video(yt, out_file, new_title, new_desc, new_tags, PRIVACY)

            # ── SAVE & CLEANUP ──
            save_history(v['id'])
            ok += 1
            if is_short:
                ok_s += 1
            else:
                ok_v += 1

            for f in [meta['file'], out_file]:
                if os.path.exists(f):
                    os.remove(f)

            # Wait between videos
            if i < len(batch) - 1:
                wait = 10
                print(f"\n⏳ Waiting {wait}s...")
                time.sleep(wait)

        except Exception as e:
            print(f"\n❌ FAILED: {e}")
            fail += 1
            _clean_files(v['id'])
            out = f"out/{v['id']}_mod.mp4"
            if os.path.exists(out):
                os.remove(out)
            continue

    # Cleanup
    if os.path.exists(COOKIES_FILE):
        os.remove(COOKIES_FILE)

    # Summary
    remaining = len(pending) - ok
    print(f"\n{'=' * 60}")
    print(f"📊 RESULTS")
    print(f"{'=' * 60}")
    print(f"   ✅ Uploaded:  {ok} (📹{ok_v} + 🎬{ok_s})")
    print(f"   ❌ Failed:    {fail}")
    print(f"   ⏳ Remaining: {remaining}")
    if remaining > 0 and ok > 0:
        runs_left = remaining // BATCH_SIZE + 1
        print(f"   🕐 ~{runs_left} more runs needed")
    elif ok == 0 and fail > 0:
        print(f"   ⚠️  All failed — re-export cookies and try again")
    elif remaining == 0:
        print(f"   🎉 ALL DONE!")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
YouTube Auto Pipeline — Local PC Version
Downloads from Channel A → Modifies → Uploads to Channel B
Tracks duplicates via YouTube API + local history file
"""
import os
import sys
import json
import time
import subprocess
import re
import glob
import base64
import yt_dlp
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from title_modifier import modify_title
from description_modifier import modify_description, modify_tags


# ==================== LOAD CONFIG ====================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

with open("config.json") as f:
    CONFIG = json.load(f)

SOURCE    = CONFIG["source_channel"]
SPEED     = CONFIG.get("speed", 1.05)
BATCH     = CONFIG.get("batch_size", 3)
PRIVACY   = CONFIG.get("privacy", "public")
ORDER     = CONFIG.get("order", "oldest")
BROWSER   = CONFIG.get("browser", "chrome")
WAIT      = CONFIG.get("wait_between_videos", 30)
HISTORY   = os.path.join(SCRIPT_DIR, "history.txt")
COOKIES   = os.path.join(SCRIPT_DIR, "cookies.txt")
MARKER    = "〔SRCID:{vid_id}〕"


class UploadLimitError(Exception):
    pass


# ==================== COOKIES SETUP ====================
def setup_cookies():
    """Decode cookies from base64 if needed."""
    if os.path.exists(COOKIES) and os.path.getsize(COOKIES) > 100:
        print("🍪 Using existing cookies.txt")
        return True

    b64_file = os.path.join(SCRIPT_DIR, "cookies_base64.txt")
    if os.path.exists(b64_file):
        try:
            with open(b64_file, "r") as f:
                b64 = f.read().strip()
            decoded = base64.b64decode(b64)
            with open(COOKIES, "wb") as f:
                f.write(decoded)
            print("🍪 Cookies decoded from base64")
            return True
        except Exception as e:
            print(f"⚠️ Cookie decode error: {e}")

    print("ℹ️ No cookies file — will use browser cookies")
    return False


# ==================== YOUTUBE API ====================
def get_youtube():
    """Connect to YouTube API for Channel B uploads."""
    token_file = os.path.join(SCRIPT_DIR, "youtube_token.json")

    if not os.path.exists(token_file):
        print("❌ youtube_token.json not found!")
        print("   Run: python setup_token.py")
        sys.exit(1)

    with open(token_file) as f:
        token = json.load(f)

    creds = Credentials(
        token=token.get('token', ''),
        refresh_token=token['refresh_token'],
        token_uri=token.get('token_uri', 'https://oauth2.googleapis.com/token'),
        client_id=token['client_id'],
        client_secret=token['client_secret'],
    )

    if creds.expired or not creds.valid:
        creds.refresh(Request())
        with open(token_file, 'w') as f:
            json.dump({
                'token': creds.token,
                'refresh_token': creds.refresh_token,
                'token_uri': creds.token_uri,
                'client_id': creds.client_id,
                'client_secret': creds.client_secret,
            }, f, indent=2)

    return build("youtube", "v3", credentials=creds)


# ==================== DUPLICATE CHECK ====================
def get_already_uploaded(yt):
    """
    Check Channel B via YouTube API.
    Reads hidden SRCID marker from descriptions.
    """
    print("\n🔍 Checking Channel B for already uploaded videos...")
    uploaded = set()

    try:
        ch = yt.channels().list(part="contentDetails", mine=True).execute()
        if not ch.get('items'):
            print("   ⚠️ Could not get Channel B info")
            return uploaded

        playlist_id = ch['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        next_page = None
        total_checked = 0

        while True:
            req = yt.playlistItems().list(
                part="snippet",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page,
            )
            resp = req.execute()

            for item in resp.get('items', []):
                desc = item['snippet'].get('description', '')
                total_checked += 1
                match = re.search(r'〔SRCID:([a-zA-Z0-9_-]+)〕', desc)
                if match:
                    uploaded.add(match.group(1))

            next_page = resp.get('nextPageToken')
            if not next_page:
                break

        print(f"   Checked {total_checked} videos on Channel B")
        print(f"   Found {len(uploaded)} with source markers")

    except Exception as e:
        print(f"   ⚠️ API error: {e}")

    return uploaded


# ==================== LOCAL HISTORY ====================
def load_history():
    """Load local history file."""
    if os.path.exists(HISTORY):
        with open(HISTORY) as f:
            return set(l.strip() for l in f if l.strip())
    return set()


def save_history(vid):
    """Save video ID to local history."""
    with open(HISTORY, "a") as f:
        f.write(vid + "\n")


# ==================== TEMP CLEANUP ====================
def cleanup_temp():
    """Remove stale temp files from previous crashed runs."""
    for d in ('dl', 'out'):
        if os.path.isdir(d):
            for fname in os.listdir(d):
                path = os.path.join(d, fname)
                try:
                    age = time.time() - os.path.getmtime(path)
                    if age > 3600:
                        os.remove(path)
                        print(f"   🗑️ Cleaned stale: {fname}")
                except OSError:
                    pass


# ==================== GET CHANNEL A CONTENT ====================
def get_channel_base(url):
    return re.sub(
        r'/(videos|shorts|streams|playlists|community|about|featured)/?$',
        '', url.strip().rstrip('/')
    )


def _build_cookie_strategies():
    """Return list of (name, extra_opts) for yt-dlp."""
    strategies = [("Browser cookies", {'cookiesfrombrowser': (BROWSER,)})]
    if os.path.exists(COOKIES):
        strategies.append(("Cookie file", {'cookiefile': COOKIES}))
    strategies.append(("No cookies", {}))
    return strategies


def _extract_entries(url, strategies):
    """Try each cookie strategy to list videos from a channel page."""
    base_opts = {
        'quiet': True,
        'extract_flat': True,
        'ignoreerrors': True,
    }
    for name, extra in strategies:
        try:
            opts = {**base_opts, **extra}
            with yt_dlp.YoutubeDL(opts) as y:
                info = y.extract_info(url, download=False)
                if info and info.get('entries'):
                    return list(info['entries'])
        except Exception as ex:
            print(f"   {name} failed: {str(ex)[:60]}")
    return []


def get_all_content():
    """Get ALL videos + shorts from Channel A."""
    base = get_channel_base(SOURCE)
    all_items = []
    seen = set()
    strategies = _build_cookie_strategies()

    for page_type in ("videos", "shorts"):
        page_url = f"{base}/{page_type}"
        vtype = "short" if page_type == "shorts" else "video"
        emoji = "🎬" if vtype == "short" else "📹"
        print(f"\n{emoji} Scanning /{page_type}...")

        entries = _extract_entries(page_url, strategies)
        for e in entries:
            if e and e.get('id') and e['id'] not in seen:
                all_items.append({
                    'id': e['id'],
                    'url': f"https://www.youtube.com/watch?v={e['id']}",
                    'title': e.get('title', 'Untitled'),
                    'type': vtype,
                })
                seen.add(e['id'])

        count = sum(1 for i in all_items if i['type'] == vtype)
        print(f"   Found: {count}")

    print(f"\n📊 Total content on Channel A: {len(all_items)}")
    return all_items


# ==================== DOWNLOAD ====================
def download(url, vid, content_type, listing_title):
    """
    Download video — NO subtitles.
    Priority: Browser cookies → Cookie file → iOS → Android
    """
    os.makedirs("dl", exist_ok=True)
    file_path = f"dl/{vid}.mp4"

    for f in glob.glob(f"dl/{vid}*"):
        try:
            os.remove(f)
        except OSError:
            pass

    strategies = [
        ("Browser cookies", _dl_browser),
        ("Cookie file", _dl_cookiefile),
        ("iOS client", _dl_ios),
        ("Android client", _dl_android),
    ]

    for name, func in strategies:
        try:
            print(f"   🔄 {name}...")
            meta = func(url, vid, file_path)

            if meta and os.path.exists(file_path) and os.path.getsize(file_path) > 10000:
                _strip_subtitle_streams(file_path)

                w, h, dur = _probe(file_path)

                title = meta.get('title', '') or ''
                if _bad_title(title):
                    title = listing_title
                if _bad_title(title):
                    title = "Amazing Video"

                meta.update({
                    'file': file_path,
                    'title': title,
                    'width': w,
                    'height': h,
                    'duration': dur,
                    'is_short': content_type == 'short' or dur <= 60 or h > w,
                })

                size = os.path.getsize(file_path) / 1024 / 1024
                print(f"   ✅ {name} OK! {size:.1f}MB | {w}x{h} | {dur:.0f}s")
                return meta

        except Exception as e:
            print(f"   ❌ {name}: {str(e)[:80]}")
            for f in glob.glob(f"dl/{vid}*"):
                try:
                    os.remove(f)
                except OSError:
                    pass

    raise Exception(f"All download methods failed for {vid}")


def _base_dl_opts(vid):
    """Shared download options — subtitles fully disabled."""
    return {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'dl/{vid}.%(ext)s',
        'merge_output_format': 'mp4',
        'quiet': False,
        'retries': 5,
        'socket_timeout': 30,
        'writesubtitles': False,
        'writeautomaticsub': False,
        'embedsubtitles': False,
        'subtitleslangs': [],
        'postprocessors': [],
    }


def _dl_browser(url, vid, output):
    """Download using browser cookies."""
    opts = _base_dl_opts(vid)
    opts['cookiesfrombrowser'] = (BROWSER,)
    return _run_ytdlp(url, vid, output, opts)


def _dl_cookiefile(url, vid, output):
    """Download using cookies.txt file."""
    if not os.path.exists(COOKIES):
        raise Exception("No cookies.txt")
    opts = _base_dl_opts(vid)
    opts['cookiefile'] = COOKIES
    return _run_ytdlp(url, vid, output, opts)


def _dl_ios(url, vid, output):
    """Download impersonating iOS client."""
    opts = _base_dl_opts(vid)
    opts['retries'] = 3
    opts['extractor_args'] = {
        'youtube': {
            'player_client': ['ios'],
            'player_skip': ['webpage', 'configs'],
        }
    }
    opts['http_headers'] = {
        'User-Agent': 'com.google.ios.youtube/19.29.1 (iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X;)',
    }
    if os.path.exists(COOKIES):
        opts['cookiefile'] = COOKIES
    return _run_ytdlp(url, vid, output, opts)


def _dl_android(url, vid, output):
    """Download impersonating Android client."""
    opts = _base_dl_opts(vid)
    opts['retries'] = 3
    opts['extractor_args'] = {
        'youtube': {
            'player_client': ['android'],
            'player_skip': ['webpage', 'configs'],
        }
    }
    opts['http_headers'] = {
        'User-Agent': 'com.google.android.youtube/19.29.37 (Linux; U; Android 14; en_US) gzip',
    }
    if os.path.exists(COOKIES):
        opts['cookiefile'] = COOKIES
    return _run_ytdlp(url, vid, output, opts)


def _run_ytdlp(url, vid, output, opts):
    """Execute yt-dlp download."""
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=True)

    if not info:
        raise Exception("No info returned")

    _fix_file(vid, output)

    if not os.path.exists(output) or os.path.getsize(output) < 10000:
        raise Exception("File missing or too small")

    # Delete any subtitle files yt-dlp may have created
    for ext in ('srt', 'vtt', 'ass', 'ssa', 'sub', 'lrc', 'json3', 'srv1', 'srv2', 'srv3', 'ttml'):
        for sf in glob.glob(f"dl/{vid}*.{ext}"):
            try:
                os.remove(sf)
            except OSError:
                pass

    return {
        'id': vid,
        'title': info.get('title', '') or '',
        'desc': info.get('description', '') or '',
        'tags': info.get('tags', []) or [],
    }


# ==================== HELPERS ====================
def _strip_subtitle_streams(file_path):
    """
    Remove ALL subtitle streams from an mp4 file.
    Prevents any soft-sub from rendering during playback or re-encode.
    """
    tmp = file_path + ".nosub.mp4"
    try:
        cmd = [
            "ffmpeg", "-y", "-i", file_path,
            "-map", "0:v",
            "-map", "0:a?",
            "-sn",
            "-c", "copy",
            tmp,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 10000:
            os.replace(tmp, file_path)
            print("   🔇 Subtitle streams stripped")
        else:
            if os.path.exists(tmp):
                os.remove(tmp)
    except Exception as e:
        print(f"   ⚠️ Subtitle strip warning: {e}")
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _fix_file(vid, target):
    """Find and rename downloaded file to target path."""
    if os.path.exists(target) and os.path.getsize(target) > 10000:
        return

    for ext in ['mp4', 'webm', 'mkv', 'flv', 'avi']:
        p = f'dl/{vid}.{ext}'
        if os.path.exists(p) and os.path.getsize(p) > 1000:
            if ext != 'mp4':
                result = subprocess.run(
                    [
                        'ffmpeg', '-y', '-i', p,
                        '-c:v', 'libx264', '-c:a', 'aac',
                        '-sn',
                        target,
                    ],
                    capture_output=True, text=True
                )
                if result.returncode != 0:
                    raise RuntimeError(f"ffmpeg remux failed: {result.stderr[-200:]}")
                os.remove(p)
            else:
                os.rename(p, target)
            return
    raise FileNotFoundError(f"No downloaded file found for {vid}")


def _bad_title(t):
    """Check if title is garbage."""
    if not t or len(t.strip()) < 2:
        return True
    bad = [r'^dl[/\\]', r'\.f\d+', r'\.mp4$', r'\.webm$', r'^\.', r'^Untitled$']
    return any(re.search(p, t, re.IGNORECASE) for p in bad) or '/' in t or '\\' in t


def _probe(path):
    """Get video dimensions and duration."""
    try:
        cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json',
               '-show_format', '-show_streams', path]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json.loads(r.stdout)
        dur = float(data.get('format', {}).get('duration', 0))
        w, h = 1920, 1080
        for s in data.get('streams', []):
            if s.get('codec_type') == 'video':
                w = int(s.get('width', 1920))
                h = int(s.get('height', 1080))
                break
        return w, h, dur
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"   ⚠️ ffprobe failed: {e}")
        return 1920, 1080, 0


# ==================== VIDEO MODIFICATION ====================
def modify_video(inp, out, speed, is_short=False):
    """
    Apply all anti-copyright modifications.
    -sn ensures NO subtitle streams in the output.
    """
    os.makedirs("out", exist_ok=True)

    if is_short:
        scale = "scale=1080:1920:force_original_aspect_ratio=decrease"
        pad = "pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
    else:
        scale = "scale=1920:1080:force_original_aspect_ratio=decrease"
        pad = "pad=1920:1080:(ow-iw)/2:(oh-ih)/2"

    vf = ",".join([
        f"setpts=PTS/{speed}",
        "hflip",
        "crop=iw*0.95:ih*0.95",
        scale, pad,
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
        "ffmpeg", "-y", "-i", inp,
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-sn",
        "-filter:v", vf,
        "-filter:a", af,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
    ]
    if is_short:
        cmd.extend(["-t", "59"])
    cmd.append(out)

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise Exception(f"FFmpeg failed: {r.stderr[-200:]}")

    _verify_no_subs(out)

    print(f"   ✅ {'Short' if is_short else 'Video'} modified (no subtitles)")


def _verify_no_subs(path):
    """Double-check the output file contains zero subtitle streams."""
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_streams', '-select_streams', 's', path,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        data = json.loads(r.stdout)
        sub_streams = data.get('streams', [])
        if sub_streams:
            print(f"   ⚠️ Found {len(sub_streams)} subtitle stream(s) — stripping again...")
            _strip_subtitle_streams(path)
    except Exception:
        pass


# ==================== UPLOAD ====================
def upload_video(yt, path, title, desc, tags, privacy):
    """Upload video to Channel B."""
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
            if 'uploadLimitExceeded' in str(e):
                raise UploadLimitError("YouTube daily upload limit reached!")
            if e.resp.status in (500, 502, 503, 504) and retry < 10:
                retry += 1
                time.sleep(min(2 ** retry, 60))
                continue
            raise
        except (ConnectionError, TimeoutError, OSError):
            retry += 1
            if retry > 10:
                raise
            time.sleep(5)

    vid_id = resp['id']
    print(f"   ✅ https://youtu.be/{vid_id}")
    return vid_id


# ==================== DEPENDENCY CHECK ====================
def check_dependencies():
    """Verify ffmpeg and ffprobe are installed."""
    for tool in ('ffmpeg', 'ffprobe'):
        try:
            r = subprocess.run([tool, '-version'], capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                raise FileNotFoundError
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print(f"❌ {tool} not found. Install it: https://ffmpeg.org/download.html")
            sys.exit(1)


# ==================== MAIN ====================
def main():
    print("=" * 60)
    print("🚀 YouTube Auto Pipeline — Local PC")
    print(f"   Source:  {SOURCE}")
    print(f"   Speed:  {SPEED}x | Batch: {BATCH}")
    print(f"   Browser: {BROWSER}")
    print("=" * 60)

    check_dependencies()
    setup_cookies()
    cleanup_temp()

    yt = get_youtube()

    # ── DUPLICATE CHECK (3 layers) ──
    api_done = get_already_uploaded(yt)
    file_done = load_history()
    already_done = api_done | file_done

    print(f"\n📜 Already uploaded: {len(already_done)} total")
    print(f"   API found:  {len(api_done)}")
    print(f"   File found: {len(file_done)}")

    for vid_id in api_done:
        if vid_id not in file_done:
            save_history(vid_id)

    # ── GET CHANNEL A CONTENT ──
    all_content = get_all_content()

    if not all_content:
        print("\n❌ No content found on Channel A!")
        print("   Check your source_channel URL in config.json")
        return 0, 0

    pending = [v for v in all_content if v['id'] not in already_done]

    if not pending:
        print("\n🎉 ALL content already uploaded! Nothing to do.")
        return 0, 0

    if ORDER == "oldest":
        pending.reverse()

    pv = sum(1 for p in pending if p.get('type') == 'video')
    ps = sum(1 for p in pending if p.get('type') == 'short')

    print(f"\n📊 Channel A: {len(all_content)} total")
    print(f"   ✅ Done:      {len(already_done)}")
    print(f"   ⏳ Remaining: {len(pending)} (📹{pv} 🎬{ps})")
    print(f"   📦 Batch:     {min(BATCH, len(pending))}")

    # ── PROCESS BATCH ──
    batch = pending[:BATCH]
    ok = fail = ok_v = ok_s = 0
    upload_limit = False

    for i, v in enumerate(batch):
        if upload_limit:
            print(f"\n⛔ Skipping — upload limit reached")
            break

        ct = v.get('type', 'video')
        is_short = ct == 'short'
        emoji = "🎬" if is_short else "📹"

        print(f"\n{'=' * 60}")
        print(f"{emoji} [{i + 1}/{len(batch)}] {v['title']}")
        print(f"   ID: {v['id']} | Type: {ct.upper()}")
        print(f"{'=' * 60}")

        if v['id'] in already_done:
            print("   ⏩ SKIP — already uploaded")
            continue

        try:
            # DOWNLOAD
            print("\n⬇️  Downloading...")
            meta = download(v['url'], v['id'], ct, v['title'])
            is_short = meta.get('is_short', is_short)

            # MODIFY VIDEO
            print("\n⚡ Modifying video...")
            out_file = f"out/{v['id']}_mod.mp4"
            modify_video(meta['file'], out_file, SPEED, is_short)

            # MODIFY TITLE
            raw_title = meta['title']
            new_title = modify_title(raw_title)
            if is_short and '#shorts' not in new_title.lower():
                if len(new_title) > 91:
                    new_title = new_title[:91] + " #Shorts"
                else:
                    new_title = new_title + " #Shorts"

            print(f"\n📝 Title:")
            print(f"   OLD: {raw_title[:50]}")
            print(f"   NEW: {new_title[:50]}")

            # MODIFY DESCRIPTION
            new_desc = modify_description(meta.get('desc', ''), new_title)
            if is_short and '#shorts' not in new_desc.lower():
                new_desc = "#Shorts\n\n" + new_desc

            marker = MARKER.format(vid_id=v['id'])
            new_desc = new_desc + f"\n\n{marker}"

            # MODIFY TAGS
            new_tags = modify_tags(meta.get('tags', []))
            if is_short:
                new_tags = list(dict.fromkeys(
                    new_tags + ["shorts", "reels", "ytshorts", "short video"]
                ))[:30]

            # UPLOAD
            print("\n📤 Uploading to Channel B...")
            upload_video(yt, out_file, new_title, new_desc, new_tags, PRIVACY)

            # MARK AS DONE
            save_history(v['id'])
            already_done.add(v['id'])
            ok += 1
            if is_short:
                ok_s += 1
            else:
                ok_v += 1

            # CLEANUP
            for f in [meta['file'], out_file]:
                if os.path.exists(f):
                    os.remove(f)

            # WAIT
            if i < len(batch) - 1:
                print(f"\n⏳ Waiting {WAIT}s before next video...")
                time.sleep(WAIT)

        except UploadLimitError:
            print(f"\n🚫 YOUTUBE UPLOAD LIMIT REACHED!")
            print(f"   Will retry in next run.")
            upload_limit = True
            for f in glob.glob(f"dl/{v['id']}*") + glob.glob(f"out/{v['id']}*"):
                try:
                    os.remove(f)
                except OSError:
                    pass

        except Exception as e:
            print(f"\n❌ FAILED: {e}")
            fail += 1
            for f in glob.glob(f"dl/{v['id']}*") + glob.glob(f"out/{v['id']}*"):
                try:
                    os.remove(f)
                except OSError:
                    pass
            continue

    # SUMMARY
    remaining = len(pending) - ok
    print(f"\n{'=' * 60}")
    print(f"📊 RESULTS")
    print(f"{'=' * 60}")
    print(f"   ✅ Uploaded:  {ok} (📹{ok_v} + 🎬{ok_s})")
    print(f"   ❌ Failed:    {fail}")
    print(f"   ⏳ Remaining: {remaining}")

    if upload_limit:
        print(f"\n   🚫 Upload limit — will retry next run")
    elif remaining > 0 and ok > 0:
        runs = remaining // BATCH + 1
        print(f"   🕐 ~{runs} more runs needed")
    elif ok == 0 and fail > 0:
        print(f"   ⚠️ All failed — check errors above")
    elif remaining == 0:
        print(f"   🎉 ALL DONE!")

    print(f"{'=' * 60}")

    return ok, fail


if __name__ == "__main__":
    ok, fail = main()
    sys.exit(0 if fail == 0 else 1)

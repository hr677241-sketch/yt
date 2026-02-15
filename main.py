import os
import sys
import json
import time
import subprocess
import re
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from title_modifier import modify_title
from description_modifier import modify_description, modify_tags


# ==================== CONFIG ====================
SOURCE_URL   = os.environ.get("SOURCE_URL", "")
SPEED        = float(os.environ.get("SPEED", "1.05"))
BATCH_SIZE   = int(os.environ.get("BATCH_SIZE", "3"))
PRIVACY      = os.environ.get("PRIVACY", "public")
HISTORY_FILE = "history.txt"
ORDER        = os.environ.get("ORDER", "oldest")

# Marker we hide in description to track which source video it came from
ORIGIN_MARKER = "〔SRCID:{vid_id}〕"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) '
                  'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 '
                  'Mobile/15E148 Safari/604.1',
}


# ==================== YOUTUBE API ====================
def get_youtube():
    """Build YouTube API client for Channel B."""
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


def get_uploaded_ids(yt):
    """
    Check Channel B for already uploaded videos.
    Reads the hidden SRCID marker from descriptions.
    This is 100% reliable — no git commit issues.
    """
    print("🔍 Checking Channel B for already uploaded videos...")
    uploaded = set()

    try:
        # Get Channel B's upload playlist
        channels = yt.channels().list(part="contentDetails", mine=True).execute()
        if not channels.get('items'):
            print("   ⚠️ Could not fetch Channel B info")
            return uploaded

        uploads_playlist = channels['items'][0]['contentDetails']['relatedPlaylists']['uploads']

        # Fetch all videos from Channel B
        next_page = None
        while True:
            request = yt.playlistItems().list(
                part="snippet",
                playlistId=uploads_playlist,
                maxResults=50,
                pageToken=next_page,
            )
            response = request.execute()

            for item in response.get('items', []):
                desc = item['snippet'].get('description', '')
                # Find our hidden marker
                match = re.search(r'〔SRCID:([a-zA-Z0-9_-]+)〕', desc)
                if match:
                    uploaded.add(match.group(1))

            next_page = response.get('nextPageToken')
            if not next_page:
                break

    except Exception as e:
        print(f"   ⚠️ API check error: {e}")

    print(f"   Found {len(uploaded)} already uploaded source IDs")
    return uploaded


# ==================== HISTORY (backup) ====================
def load_history():
    """Local file history as backup."""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            return set(l.strip() for l in f if l.strip())
    return set()


def save_history(vid):
    with open(HISTORY_FILE, "a") as f:
        f.write(vid + "\n")


# ==================== CHANNEL A LISTING ====================
def get_channel_base(url):
    return re.sub(
        r'/(videos|shorts|streams|playlists|community|about|featured)/?$',
        '', url.strip().rstrip('/')
    )


def get_all_content(url):
    """Get all video IDs from Channel A using web scraping."""
    base = get_channel_base(url)
    all_items = []
    seen = set()

    for page_type in ["videos", "shorts"]:
        vtype = "short" if page_type == "shorts" else "video"
        emoji = "🎬" if vtype == "short" else "📹"
        print(f"\n{emoji} Scanning /{page_type}...")

        page_url = f"{base}/{page_type}"
        items = _scrape_channel_page(page_url)

        for vid_id, title in items:
            if vid_id not in seen:
                all_items.append({
                    'id': vid_id,
                    'url': f"https://www.youtube.com/watch?v={vid_id}",
                    'title': title,
                    'type': vtype,
                })
                seen.add(vid_id)

        print(f"   Found: {len(items)}")

    print(f"\n📊 Total content on Channel A: {len(all_items)}")
    return all_items


def _scrape_channel_page(url):
    """Extract video IDs from channel page HTML."""
    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return results

        html = r.text

        # Extract video IDs and titles from the page JSON data
        # YouTube embeds initial data as JSON in the page
        pattern = r'"videoId"\s*:\s*"([a-zA-Z0-9_-]{11})"'
        ids = re.findall(pattern, html)

        # Extract titles
        title_pattern = r'"title"\s*:\s*\{\s*"runs"\s*:\s*\[\s*\{\s*"text"\s*:\s*"([^"]+)"'
        titles = re.findall(title_pattern, html)

        seen = set()
        for i, vid_id in enumerate(ids):
            if vid_id not in seen and len(vid_id) == 11:
                title = titles[i] if i < len(titles) else "Untitled"
                results.append((vid_id, title))
                seen.add(vid_id)

    except Exception as e:
        print(f"   ⚠️ Scrape error: {e}")

    return results


# ==================== DOWNLOAD ====================
def download(url, vid):
    """
    Download video using multiple methods.
    Priority: pytubefix → Cobalt API → yt-dlp
    """
    os.makedirs("dl", exist_ok=True)
    file_path = f"dl/{vid}.mp4"
    _clean(vid)

    methods = [
        ("pytubefix", lambda: _dl_pytubefix(url, vid, file_path)),
        ("Cobalt API", lambda: _dl_cobalt(vid, file_path)),
        ("yt-dlp iOS", lambda: _dl_ytdlp(url, vid, file_path, "ios")),
        ("yt-dlp Android", lambda: _dl_ytdlp(url, vid, file_path, "android")),
    ]

    for name, func in methods:
        try:
            print(f"   🔄 {name}...")
            meta = func()
            if meta and os.path.exists(file_path) and os.path.getsize(file_path) > 10000:
                w, h, dur = _probe(file_path)
                meta.update({
                    'file': file_path, 'width': w, 'height': h,
                    'duration': dur,
                    'is_short': dur <= 60 or h > w,
                })
                size_mb = os.path.getsize(file_path) / 1024 / 1024
                print(f"   ✅ {name} OK! {size_mb:.1f}MB | {w}x{h} | {dur:.0f}s")
                return meta
        except Exception as e:
            print(f"   ❌ {name}: {str(e)[:80]}")
            _clean(vid)
    
    raise Exception(f"All download methods failed for {vid}")


def _dl_pytubefix(url, vid, output):
    """Download using pytubefix library."""
    from pytubefix import YouTube
    from pytubefix.cli import on_progress

    yt = YouTube(url, on_progress_callback=on_progress)

    # Try progressive streams first (video + audio combined)
    stream = yt.streams.filter(
        progressive=True, file_extension='mp4'
    ).order_by('resolution').desc().first()

    if not stream:
        # Try adaptive (video only, need to merge audio)
        video_stream = yt.streams.filter(
            adaptive=True, file_extension='mp4', only_video=True
        ).order_by('resolution').desc().first()

        audio_stream = yt.streams.filter(
            adaptive=True, only_audio=True
        ).order_by('abr').desc().first()

        if video_stream and audio_stream:
            v_path = video_stream.download(output_path="dl", filename=f"{vid}_v")
            a_path = audio_stream.download(output_path="dl", filename=f"{vid}_a")

            # Merge with ffmpeg
            cmd = ['ffmpeg', '-y', '-i', v_path, '-i', a_path,
                   '-c:v', 'copy', '-c:a', 'aac', output]
            subprocess.run(cmd, capture_output=True, check=True)

            for f in [v_path, a_path]:
                if os.path.exists(f):
                    os.remove(f)
        elif video_stream:
            video_stream.download(output_path="dl", filename=f"{vid}.mp4")
        else:
            raise Exception("No streams available")
    else:
        stream.download(output_path="dl", filename=f"{vid}.mp4")

    # Handle if pytubefix saved with different name
    if not os.path.exists(output):
        for f in os.listdir("dl"):
            if f.startswith(vid) and not f.endswith('.part'):
                full = os.path.join("dl", f)
                if full != output:
                    if not f.endswith('.mp4'):
                        _to_mp4(full, output)
                    else:
                        os.rename(full, output)
                break

    if not os.path.exists(output):
        raise Exception("File not found after download")

    return {
        'id': vid,
        'title': yt.title or 'Untitled',
        'desc': yt.description or '',
        'tags': yt.keywords or [],
    }


def _dl_cobalt(vid, output):
    """Download using Cobalt API."""
    api_url = "https://api.cobalt.tools"

    payload = {
        "url": f"https://www.youtube.com/watch?v={vid}",
        "downloadMode": "auto",
        "filenameStyle": "basic",
    }

    cobalt_headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'User-Agent': HEADERS['User-Agent'],
    }

    r = requests.post(f"{api_url}/", json=payload,
                      headers=cobalt_headers, timeout=30)

    if r.status_code != 200:
        raise Exception(f"Cobalt API returned {r.status_code}")

    data = r.json()
    status = data.get('status', '')

    dl_url = None
    if status in ('tunnel', 'redirect', 'stream'):
        dl_url = data.get('url', '')
    elif status == 'picker':
        picker = data.get('picker', [])
        if picker:
            dl_url = picker[0].get('url', '')

    if not dl_url:
        raise Exception(f"Cobalt no URL. Status: {status}")

    # Download the file
    r = requests.get(dl_url, headers=HEADERS, stream=True, timeout=300)
    r.raise_for_status()

    with open(output, 'wb') as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)

    if not output.endswith('.mp4') or _needs_convert(output):
        tmp = output + ".tmp"
        os.rename(output, tmp)
        _to_mp4(tmp, output)

    return {
        'id': vid, 'title': 'Untitled', 'desc': '', 'tags': [],
    }


def _dl_ytdlp(url, vid, output, client):
    """Download using yt-dlp as fallback."""
    import yt_dlp

    opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'dl/{vid}.%(ext)s',
        'merge_output_format': 'mp4',
        'quiet': True,
        'ignoreerrors': False,
        'retries': 3,
        'socket_timeout': 30,
        'extractor_args': {
            'youtube': {
                'player_client': [client],
                'player_skip': ['webpage', 'configs'],
            }
        },
        'http_headers': HEADERS,
    }

    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=True)

    if not info:
        raise Exception("No info")

    found = _find(vid)
    if found and found != output:
        if not found.endswith('.mp4'):
            _to_mp4(found, output)
        else:
            os.rename(found, output)

    if not os.path.exists(output) or os.path.getsize(output) < 10000:
        raise Exception("File missing")

    return {
        'id': vid,
        'title': info.get('title', 'Untitled'),
        'desc': info.get('description', ''),
        'tags': info.get('tags', []) or [],
    }


# ==================== HELPERS ====================
def _find(vid):
    for ext in ['mp4', 'webm', 'mkv', 'flv', 'avi', '3gp']:
        p = f'dl/{vid}.{ext}'
        if os.path.exists(p) and os.path.getsize(p) > 1000:
            return p
    return None


def _clean(vid):
    for ext in ['mp4', 'webm', 'mkv', 'part', 'flv', 'avi',
                'f251.webm', 'f140.m4a', 'tmp']:
        p = f'dl/{vid}.{ext}'
        if os.path.exists(p):
            os.remove(p)
    for suffix in ['_v', '_a', '_v.mp4', '_a.mp4',
                    '_v.webm', '_a.webm', '_v.m4a', '_a.m4a']:
        p = f'dl/{vid}{suffix}'
        if os.path.exists(p):
            os.remove(p)


def _to_mp4(inp, out):
    subprocess.run(['ffmpeg', '-y', '-i', inp,
                    '-c:v', 'libx264', '-c:a', 'aac', out],
                   capture_output=True)
    if os.path.exists(out) and os.path.exists(inp) and inp != out:
        os.remove(inp)


def _needs_convert(path):
    """Check if file needs conversion."""
    try:
        r = subprocess.run(['ffprobe', '-v', 'quiet', '-print_format', 'json',
                           '-show_format', path],
                          capture_output=True, text=True)
        data = json.loads(r.stdout)
        fmt = data.get('format', {}).get('format_name', '')
        return 'mp4' not in fmt
    except:
        return False


def _probe(path):
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


# ==================== VIDEO MODIFICATION ====================
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
        "-filter:v", vf, "-filter:a", af,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
    ]

    if is_short:
        cmd.extend(["-t", "59"])

    cmd.append(out)

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise Exception(f"FFmpeg: {r.stderr[-200:]}")

    print(f"   ✅ {'Short' if is_short else 'Video'} modified")


# ==================== UPLOAD ====================
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


# ==================== MAIN ====================
def main():
    print("=" * 60)
    print("🚀 YouTube Auto Pipeline — Final Version")
    print("   pytubefix + Cobalt + YouTube API duplicate check")
    print("=" * 60)

    if not SOURCE_URL:
        sys.exit("❌ SOURCE_URL not set!")

    # Connect to YouTube API
    yt = get_youtube()

    # === DUPLICATE CHECK ===
    # Method 1: Check Channel B via API (100% reliable)
    api_done = get_uploaded_ids(yt)

    # Method 2: Local history file (backup)
    file_done = load_history()

    # Combine both
    already_done = api_done | file_done
    print(f"📜 Total already done: {len(already_done)}")
    print(f"   (API: {len(api_done)} | File: {len(file_done)})")

    # Sync: add API results to local file
    for vid_id in api_done:
        if vid_id not in file_done:
            save_history(vid_id)

    # === GET CHANNEL A CONTENT ===
    all_content = get_all_content(SOURCE_URL)
    if not all_content:
        sys.exit("❌ No content found on Channel A")

    # Filter pending
    pending = [v for v in all_content if v['id'] not in already_done]

    if not pending:
        print("\n🎉 ALL content already uploaded! Nothing to do.")
        return

    if ORDER == "oldest":
        pending.reverse()

    pv = len([p for p in pending if p.get('type') == 'video'])
    ps = len([p for p in pending if p.get('type') == 'short'])

    print(f"\n📊 Channel A: {len(all_content)} total")
    print(f"   ✅ Already done: {len(already_done)}")
    print(f"   ⏳ Remaining: {len(pending)} (📹{pv} 🎬{ps})")
    print(f"   📦 This batch: {min(BATCH_SIZE, len(pending))}")

    # === PROCESS BATCH ===
    batch = pending[:BATCH_SIZE]
    ok = fail = ok_v = ok_s = 0

    for i, v in enumerate(batch):
        ct = v.get('type', 'video')
        emoji = "🎬" if ct == 'short' else "📹"

        print(f"\n{'=' * 60}")
        print(f"{emoji} [{i + 1}/{len(batch)}] {v['title']}")
        print(f"   ID: {v['id']} | Type: {ct.upper()}")
        print(f"{'=' * 60}")

        # Double-check not already done
        if v['id'] in already_done:
            print("   ⏩ Already uploaded — skipping")
            continue

        try:
            # DOWNLOAD
            print("\n⬇️  Downloading...")
            meta = download(v['url'], v['id'])
            content_type = detect_type(meta, ct)
            is_short = content_type == 'short'

            # MODIFY VIDEO
            print("\n⚡ Modifying...")
            out_file = f"out/{v['id']}_mod.mp4"
            modify_video(meta['file'], out_file, SPEED, is_short)

            # MODIFY TITLE
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

            # MODIFY DESCRIPTION
            new_desc = modify_description(meta.get('desc', ''), new_title)
            if is_short and '#shorts' not in new_desc.lower():
                new_desc = "#Shorts\n\n" + new_desc

            # Add hidden source ID marker (for duplicate detection)
            marker = ORIGIN_MARKER.format(vid_id=v['id'])
            new_desc = new_desc + f"\n\n{marker}"

            # MODIFY TAGS
            new_tags = modify_tags(meta.get('tags', []))
            if is_short:
                new_tags = list(dict.fromkeys(
                    new_tags + ["shorts", "reels", "ytshorts", "short video"]
                ))[:30]

            # UPLOAD
            print("\n📤 Uploading...")
            upload_video(yt, out_file, new_title, new_desc, new_tags, PRIVACY)

            # SAVE TO HISTORY + MARK DONE
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
                print(f"\n⏳ Waiting 10s...")
                time.sleep(10)

        except Exception as e:
            print(f"\n❌ FAILED: {e}")
            fail += 1
            _clean(v['id'])
            out = f"out/{v['id']}_mod.mp4"
            if os.path.exists(out):
                os.remove(out)
            continue

    # SUMMARY
    remaining = len(pending) - ok
    print(f"\n{'=' * 60}")
    print(f"📊 RESULTS")
    print(f"{'=' * 60}")
    print(f"   ✅ Uploaded:  {ok} (📹{ok_v} + 🎬{ok_s})")
    print(f"   ❌ Failed:    {fail}")
    print(f"   ⏳ Remaining: {remaining}")

    if remaining > 0 and ok > 0:
        runs = remaining // BATCH_SIZE + 1
        print(f"   🕐 ~{runs} more auto-runs needed")
    elif ok == 0 and fail > 0:
        print(f"   ⚠️ All failed — check logs above")
    elif remaining == 0:
        print(f"   🎉 ALL DONE!")

    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

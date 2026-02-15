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

# ============ AUTH SETUP ============
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
    return re.sub(r'/(videos|shorts|streams|playlists|community|about|featured)/?$', '', url.strip().rstrip('/'))

def get_all_content(url):
    base_url = get_channel_base(url)
    all_content = []
    seen = set()

    # Use basic yt-dlp to just list IDs (this usually isn't blocked as aggressively)
    opts = {
        'quiet': True,
        'extract_flat': True,
        'ignoreerrors': True,
    }
    
    for page_type in ['videos', 'shorts']:
        page_url = f"{base_url}/{page_type}"
        vtype = 'short' if page_type == 'shorts' else 'video'
        print(f"\nScanning {page_type}...")
        
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(page_url, download=False)
            if info:
                for e in info.get('entries', []):
                    if e and e.get('id') and e['id'] not in seen:
                        all_content.append({
                            'id': e['id'],
                            'url': f"https://www.youtube.com/watch?v={e['id']}",
                            'title': e.get('title', 'Untitled'),
                            'type': vtype,
                        })
                        seen.add(e['id'])
        print(f"Found {len(all_content)} total so far")

    return all_content

# ============ FAST DOWNLOAD (iOS + PO TOKEN) ============
def download(url, vid):
    os.makedirs("dl", exist_ok=True)
    
    # Clean up
    for ext in ['mp4', 'webm', 'mkv']:
        if os.path.exists(f'dl/{vid}.{ext}'):
            os.remove(f'dl/{vid}.{ext}')

    print(f"   🔄 Downloading using iOS Client Impersonation...")

    # Options to impersonate an iPhone (less restrictions)
    opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'dl/{vid}.%(ext)s',
        'merge_output_format': 'mp4',
        'quiet': False,
        'no_warnings': False,
        'ignoreerrors': False,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android', 'web'], # Try iOS first, it's usually fastest/unblocked
                'player_skip': ['webpage', 'configs', 'js'], # Skip stuff we don't need to speed up
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
        }
    }

    if os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE

    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=True)
            
            # Find file
            file_path = f'dl/{vid}.mp4'
            if not os.path.exists(file_path):
                 # Fallback search
                 for f in os.listdir('dl'):
                     if f.startswith(vid):
                         file_path = os.path.join('dl', f)
                         break
            
            if os.path.exists(file_path):
                # Get dimensions
                w, h, dur = get_video_info(file_path)
                
                print(f"   ✅ Downloaded! ({os.path.getsize(file_path)/1024/1024:.1f} MB)")
                return {
                    'id': vid,
                    'title': info.get('title', 'Untitled'),
                    'desc': info.get('description', ''),
                    'tags': info.get('tags', []) or [],
                    'file': file_path,
                    'width': w, 'height': h, 'duration': dur,
                    'is_short': (dur <= 60) or (h > w),
                }
    except Exception as e:
        print(f"   ❌ iOS method failed: {str(e)[:100]}")

    # BACKUP: Android Client (if iOS fails)
    print(f"   🔄 Trying Android Client Backup...")
    try:
        opts['extractor_args']['youtube']['player_client'] = ['android']
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=True)
            file_path = f'dl/{vid}.mp4'
            if os.path.exists(file_path):
                 w, h, dur = get_video_info(file_path)
                 return {
                    'id': vid, 'title': info.get('title', 'Untitled'),
                    'desc': info.get('description', ''), 'tags': info.get('tags', []),
                    'file': file_path, 'width': w, 'height': h, 'duration': dur,
                    'is_short': (dur <= 60) or (h > w),
                }
    except Exception as e:
        raise Exception(f"All fast download methods failed: {str(e)[:100]}")

def get_video_info(path):
    try:
        cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', path]
        r = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(r.stdout)
        dur = float(data.get('format', {}).get('duration', 0))
        w, h = 1920, 1080
        for s in data.get('streams', []):
            if s.get('codec_type') == 'video':
                w = int(s.get('width', 1920)); h = int(s.get('height', 1080)); break
        return w, h, dur
    except:
        return 1920, 1080, 0

# ============ MODIFY ============
def detect_type(meta, original_type):
    if original_type == 'short': return 'short'
    if meta.get('is_short', False): return 'short'
    if meta.get('height', 0) > meta.get('width', 0): return 'short'
    return 'video'

def modify_regular_video(inp, out, speed):
    os.makedirs("out", exist_ok=True)
    vf = f"setpts=PTS/{speed},hflip,crop=iw*0.95:ih*0.95,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,eq=brightness=0.04:contrast=1.06:saturation=1.08,unsharp=5:5:0.8:5:5:0.4"
    af = f"atempo={speed},asetrate=44100*1.02,aresample=44100,bass=g=3:f=110"
    cmd = ["ffmpeg", "-y", "-i", inp, "-filter:v", vf, "-filter:a", af, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)
    print("✅ Video modified")

def modify_short_video(inp, out, speed):
    os.makedirs("out", exist_ok=True)
    vf = f"setpts=PTS/{speed},hflip,crop=iw*0.95:ih*0.95,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,eq=brightness=0.04:contrast=1.06:saturation=1.08,unsharp=5:5:0.8:5:5:0.4"
    af = f"atempo={speed},asetrate=44100*1.02,aresample=44100,bass=g=3:f=110"
    cmd = ["ffmpeg", "-y", "-i", inp, "-filter:v", vf, "-filter:a", af, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-c:a", "aac", "-b:a", "192k", "-t", "59", "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)
    print("✅ Short modified")

# ============ UPLOAD ============
def get_youtube():
    token_str = os.environ.get("YOUTUBE_TOKEN", "")
    if not token_str: sys.exit("❌ YOUTUBE_TOKEN not set")
    token = json.loads(token_str)
    creds = Credentials(token=token.get('token',''), refresh_token=token['refresh_token'], token_uri=token.get('token_uri','https://oauth2.googleapis.com/token'), client_id=token['client_id'], client_secret=token['client_secret'])
    return build("youtube", "v3", credentials=creds)

def upload_video(yt, path, title, desc, tags, privacy):
    body = {'snippet': {'title': title[:100], 'description': desc[:5000], 'tags': tags[:30], 'categoryId': '22'}, 'status': {'privacyStatus': privacy, 'selfDeclaredMadeForKids': False}}
    media = MediaFileUpload(path, mimetype='video/mp4', resumable=True, chunksize=10*1024*1024)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    retry = 0
    while resp is None:
        try:
            status, resp = req.next_chunk()
            if status: print(f"   {int(status.progress()*100)}%")
        except HttpError as e:
            if e.resp.status in [500,502,503,504]:
                retry += 1
                if retry > 10: raise
                time.sleep(2**retry)
                continue
            raise
        except:
            retry += 1; time.sleep(5)
    print(f"✅ Uploaded → https://youtu.be/{resp['id']}")

# ============ MAIN ============
def main():
    print("="*60); print("🚀 YouTube Automation — iOS Impersonation (Fast Mode)"); print("="*60)
    if not SOURCE_URL: sys.exit("❌ SOURCE_URL not set")
    setup_cookies()
    history = load_history()
    all_content = get_all_content(SOURCE_URL)
    if not all_content: sys.exit("❌ No content found")
    pending = [v for v in all_content if v['id'] not in history]
    if not pending: print("🎉 ALL content uploaded!"); return
    if ORDER == "oldest": pending.reverse()
    
    batch = pending[:BATCH_SIZE]
    yt = get_youtube()
    ok = 0
    
    for i, v in enumerate(batch):
        try:
            ct = v.get('type', 'video')
            print(f"\n{'='*60}\n[{i+1}/{len(batch)}] {v['title']}\n{'='*60}")
            
            meta = download(v['url'], v['id'])
            content_type = detect_type(meta, ct)
            
            out_file = f"out/{v['id']}_mod.mp4"
            if content_type == 'short': modify_short_video(meta['file'], out_file, SPEED)
            else: modify_regular_video(meta['file'], out_file, SPEED)
            
            new_title = modify_title(meta.get('title', 'Untitled'))
            if content_type == 'short' and '#shorts' not in new_title.lower(): new_title = (new_title[:91] + " #Shorts")
            
            new_desc = modify_description(meta.get('desc', ''), new_title)
            if content_type == 'short' and '#shorts' not in new_desc.lower(): new_desc = "#Shorts\n\n" + new_desc
            
            new_tags = modify_tags(meta.get('tags', []))
            if content_type == 'short': new_tags = list(dict.fromkeys(new_tags + ["shorts","reels"]))[:30]
            
            print("📤 Uploading...")
            upload_video(yt, out_file, new_title, new_desc, new_tags, PRIVACY)
            save_history(v['id'])
            ok += 1
            
            for f in [meta['file'], out_file]: 
                if os.path.exists(f): os.remove(f)
                
            if i < len(batch)-1: time.sleep(10) # Faster wait time
            
        except Exception as e:
            print(f"❌ FAILED: {e}")
            
    if os.path.exists(COOKIES_FILE): os.remove(COOKIES_FILE)
    print(f"\n✅ Batch Done: {ok} uploaded")

if __name__ == "__main__":
    main()

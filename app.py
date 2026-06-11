#!/usr/bin/env python3
"""
DR SHEMA Media Empire - Video Builder Service
- Real images from Wikipedia for each topic
- Ken Burns cinematic zoom effect
- Professional thumbnail with topic image
- Doctor Shema (never DR Shema)
- 3-5 minute videos
- DR SHEMA watermark on every video
"""

from flask import Flask, request, jsonify
import subprocess, os, tempfile, urllib.request, base64, json, re

app = Flask(__name__)
LOGO_PATH = "/app/logo.png"

def download_file(url, dest):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as r, open(dest, 'wb') as f:
            f.write(r.read())
        return os.path.getsize(dest) > 1000
    except Exception as e:
        print(f"Download failed: {e}")
        return False

def search_wikipedia_image(topic):
    try:
        clean = topic.replace(' ', '_')
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{clean}"
        req = urllib.request.Request(url, headers={'User-Agent': 'DrShemaBot/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            if data.get('thumbnail') and data['thumbnail'].get('source'):
                return data['thumbnail']['source']
    except:
        pass
    return None

def build_video(data):
    tmp = tempfile.mkdtemp(prefix='drshema_')
    title = data.get('title', 'Doctor Shema News')
    script = data.get('script', '')
    channel = data.get('channel', 'news')
    topic = data.get('topic', title)
    keywords = data.get('keywords', [])

    # Always say Doctor Shema not DR Shema
    script = re.sub(r'\bDR\.?\s*SHEMA\b', 'Doctor Shema', script, flags=re.IGNORECASE)
    script = re.sub(r'\bDr\.?\s*Shema\b', 'Doctor Shema', script)

    print(f"Building: {title}")

    # Get real images from Wikipedia
    images = []
    all_topics = [topic] + keywords[:4]
    for i, t in enumerate(all_topics):
        img_url = search_wikipedia_image(t)
        if img_url:
            dest = os.path.join(tmp, f'img_{i}.jpg')
            if download_file(img_url, dest):
                images.append(dest)
                print(f"Got image for: {t}")

    # Pexels backup
    for i, url in enumerate([data.get('clip1_url',''), data.get('clip2_url',''), data.get('clip3_url','')]):
        if url:
            dest = os.path.join(tmp, f'pexels_{i}.mp4')
            if download_file(url, dest):
                frame = os.path.join(tmp, f'frame_{i}.jpg')
                subprocess.run(['ffmpeg','-i',dest,'-ss','00:00:02','-frames:v','1',frame,'-y'], capture_output=True, timeout=30)
                if os.path.exists(frame):
                    images.append(frame)

    # Fallback dark background
    if not images:
        fb = os.path.join(tmp, 'bg.jpg')
        subprocess.run(['ffmpeg','-f','lavfi','-i','color=c=0x0a0a1a:size=1920x1080','-frames:v','1',fb,'-y'], capture_output=True)
        images.append(fb)

    print(f"Total images: {len(images)}")

    # Generate voice
    clean_script = re.sub(r"[^\w\s.,!?-]", ' ', script)[:5000]
    script_file = os.path.join(tmp, 'script.txt')
    audio_wav = os.path.join(tmp, 'audio.wav')
    audio_mp3 = os.path.join(tmp, 'audio.mp3')
    with open(script_file, 'w') as f:
        f.write(clean_script)

    has_audio = False
    try:
        subprocess.run(['flite','-voice','rms','-f',script_file,'-o',audio_wav], timeout=180, check=True, capture_output=True)
        subprocess.run(['ffmpeg','-i',audio_wav,'-codec:a','libmp3lame','-qscale:a','2',audio_mp3,'-y'], timeout=30, check=True, capture_output=True)
        has_audio = os.path.exists(audio_mp3) and os.path.getsize(audio_mp3) > 100
        print("Voice generated")
    except Exception as e:
        print(f"Voice error: {e}")

    # Get audio duration
    total_duration = 180
    if has_audio:
        try:
            r = subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',audio_mp3], capture_output=True, text=True, timeout=10)
            total_duration = float(r.stdout.strip())
        except:
            pass

    dur_per_img = max(5, total_duration / len(images))

    # Ken Burns effect per image
    clips = []
    for i, img in enumerate(images):
        clip_out = os.path.join(tmp, f'clip_{i}.mp4')
        frames = int(dur_per_img * 25)
        if i % 2 == 0:
            vf = f"scale=8000:-1,zoompan=z='min(zoom+0.0015,1.5)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080,setsar=1"
        else:
            vf = f"scale=8000:-1,zoompan=z='if(lte(zoom,1.0),1.5,max(1.001,zoom-0.0015))':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080,setsar=1"
        r = subprocess.run(['ffmpeg','-loop','1','-i',img,'-vf',vf,'-t',str(dur_per_img),'-c:v','libx264','-r','25','-pix_fmt','yuv420p',clip_out,'-y'], capture_output=True, timeout=120)
        if os.path.exists(clip_out) and os.path.getsize(clip_out) > 1000:
            clips.append(clip_out)

    if not clips:
        return None, None

    # Concatenate
    concat_file = os.path.join(tmp, 'concat.txt')
    concat_out = os.path.join(tmp, 'concat.mp4')
    with open(concat_file, 'w') as f:
        for c in clips:
            f.write(f"file '{c}'\n")
    subprocess.run(['ffmpeg','-f','concat','-safe','0','-i',concat_file,'-c','copy',concat_out,'-y'], capture_output=True, timeout=120)

    if not os.path.exists(concat_out):
        return None, None

    # Channel colors
    colors = {'news':'0xFF0000','heroes':'0xFFD700','africa':'0x00AA00','motivation':'0xFF6600','advice':'0x0066FF','sports':'0xFF0000'}
    bar_color = colors.get(channel, '0xFF0000')
    safe_title = re.sub(r"[^a-zA-Z0-9 ]", ' ', title)[:50].strip()
    has_logo = os.path.exists(LOGO_PATH)

    output = os.path.join(tmp, 'final.mp4')
    cmd = ['ffmpeg', '-i', concat_out]
    if has_logo:
        cmd += ['-i', LOGO_PATH]
    if has_audio:
        cmd += ['-i', audio_mp3]

    if has_logo:
        fc = (f"[0:v]scale=1920:1080,setsar=1[vb];[1:v]scale=150:150[lg];[vb][lg]overlay=W-160:10[vl];"
              f"[vl]drawtext=text='Doctor Shema':fontsize=24:fontcolor=gold:bordercolor=black:borderw=2:x=W-155:y=165[vt];"
              f"[vt]drawrect=x=0:y=H-60:w=W:h=60:color={bar_color}@0.9[vbar];"
              f"[vbar]drawtext=text='{safe_title}':fontsize=28:fontcolor=white:bordercolor=black:borderw=2:x=(W-text_w)/2:y=H-46[vf]")
    else:
        fc = (f"[0:v]scale=1920:1080,setsar=1[vb];"
              f"[vb]drawtext=text='Doctor Shema':fontsize=32:fontcolor=gold:bordercolor=black:borderw=3:x=20:y=20[vt];"
              f"[vt]drawrect=x=0:y=H-60:w=W:h=60:color={bar_color}@0.9[vbar];"
              f"[vbar]drawtext=text='{safe_title}':fontsize=28:fontcolor=white:bordercolor=black:borderw=2:x=(W-text_w)/2:y=H-46[vf]")

    cmd += ['-filter_complex', fc, '-map', '[vf]']
    if has_audio:
        audio_idx = 2 if has_logo else 1
        cmd += ['-map', f'{audio_idx}:a']
    cmd += ['-c:v','libx264','-preset','fast','-c:a','aac' if has_audio else 'copy','-shortest','-r','25',output,'-y']

    subprocess.run(cmd, capture_output=True, timeout=600)

    if not os.path.exists(output) or os.path.getsize(output) < 10000:
        return None, None

    # Professional thumbnail with real image
    thumb_path = os.path.join(tmp, 'thumbnail.jpg')
    channel_labels = {'news':'BREAKING NEWS','heroes':'WORLD HEROES','africa':'AFRICA RISING','motivation':'DAILY MOTIVATION','advice':'ADVICE OF THE DAY','sports':'SPORTS NEWS'}
    label = channel_labels.get(channel, 'DOCTOR SHEMA')
    safe_label = label.replace("'", ' ')
    short_title = re.sub(r"[^a-zA-Z0-9 ]", ' ', title)[:35].strip()

    if images and images[0] != os.path.join(tmp, 'bg.jpg'):
        thumb_cmd = ['ffmpeg','-i',images[0],'-vf',(
            f"scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,"
            f"colorchannelmixer=rr=0.4:gg=0.4:bb=0.4,"
            f"drawrect=x=0:y=0:w=W:h=110:color={bar_color}@0.95,"
            f"drawtext=text='{safe_label}':fontsize=52:fontcolor=white:bordercolor=black:borderw=3:x=(W-text_w)/2:y=28,"
            f"drawrect=x=0:y=H-130:w=W:h=130:color=black@0.88,"
            f"drawtext=text='{short_title}':fontsize=46:fontcolor=white:bordercolor=black:borderw=3:x=(W-text_w)/2:y=H-105,"
            f"drawtext=text='Doctor Shema':fontsize=30:fontcolor=gold:bordercolor=black:borderw=2:x=(W-text_w)/2:y=H-48"
        ),'-frames:v','1',thumb_path,'-y']
    else:
        thumb_cmd = ['ffmpeg','-f','lavfi','-i','color=c=0x0a0a1a:size=1280x720','-vf',(
            f"drawrect=x=0:y=0:w=W:h=110:color={bar_color}@0.95,"
            f"drawtext=text='{safe_label}':fontsize=52:fontcolor=white:bordercolor=black:borderw=3:x=(W-text_w)/2:y=28,"
            f"drawtext=text='{short_title}':fontsize=54:fontcolor=white:bordercolor=black:borderw=4:x=(W-text_w)/2:y=(H-text_h)/2,"
            f"drawrect=x=0:y=H-90:w=W:h=90:color=black@0.9,"
            f"drawtext=text='Doctor Shema':fontsize=38:fontcolor=gold:bordercolor=black:borderw=2:x=(W-text_w)/2:y=H-65"
        ),'-frames:v','1',thumb_path,'-y']

    subprocess.run(thumb_cmd, capture_output=True, timeout=30)

    with open(output,'rb') as f:
        video_b64 = base64.b64encode(f.read()).decode()
    thumb_b64 = ''
    if os.path.exists(thumb_path):
        with open(thumb_path,'rb') as f:
            thumb_b64 = base64.b64encode(f.read()).decode()

    size_mb = os.path.getsize(output)/(1024*1024)
    print(f"Done: {size_mb:.1f}MB")
    return video_b64, thumb_b64

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'Doctor Shema Video Service Running', 'ready': True})

@app.route('/build', methods=['POST'])
def build():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data'}), 400
        video_b64, thumb_b64 = build_video(data)
        if video_b64:
            return jsonify({'success': True, 'video': video_b64, 'thumbnail': thumb_b64})
        return jsonify({'success': False, 'error': 'Build failed'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8765))
    app.run(host='0.0.0.0', port=port)

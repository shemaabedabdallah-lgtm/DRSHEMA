from flask import Flask, request, jsonify
import subprocess
import tempfile
import os
import requests
import asyncio
import traceback
import json
import base64
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

VOICE = "en-US-ChristopherNeural"
GDRIVE_FOLDER_ID = "1yGoGX3f9zrsK_uJjcgOjugngu0x5TDsA"
LOGO_URL = "https://raw.githubusercontent.com/shemaabedabdallah-lgtm/DRSHEMA/main/logo.png"

CHANNEL_THEMES = {
    'news':            {'accent': (220, 30,  30),  'badge': 'BREAKING NEWS',   'bg': (15, 10, 10)},
    'motivation':      {'accent': (255, 140, 0),   'badge': 'MUST WATCH',      'bg': (15, 12, 5)},
    'advice':          {'accent': (30,  120, 220), 'badge': 'LIFE CHANGING',   'bg': (8,  12, 20)},
    'heroes':          {'accent': (212, 175, 55),  'badge': 'WORLD HEROES',    'bg': (12, 10, 5)},
    'africa':          {'accent': (50,  180, 50),  'badge': 'AFRICA RISING',   'bg': (5,  15, 5)},
    'sports':          {'accent': (0,   180, 120), 'badge': 'SPORTS UPDATE',   'bg': (5,  15, 15)},
    'sports_analysis': {'accent': (150, 50,  220), 'badge': 'MATCH ANALYSIS',  'bg': (10, 5,  20)},
}

def get_drive_service():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
        if not creds_json:
            return None
        creds_dict = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=['https://www.googleapis.com/auth/drive.file']
        )
        return build('drive', 'v3', credentials=credentials)
    except Exception as e:
        print(f"[DRIVE] Service error: {e}")
        return None

def upload_to_drive(file_path, title, mime_type='video/mp4'):
    try:
        from googleapiclient.http import MediaFileUpload
        service = get_drive_service()
        if not service:
            return None
        ext = '.jpg' if 'image' in mime_type else '.mp4'
        file_metadata = {
            'name': f"{title}{ext}",
            'parents': [GDRIVE_FOLDER_ID],
            'mimeType': mime_type
        }
        media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
        file = service.files().create(
            body=file_metadata, media_body=media, fields='id,name'
        ).execute()
        print(f"[DRIVE] ✅ Uploaded: {file['name']}")
        return file['id']
    except Exception as e:
        print(f"[DRIVE] Upload failed: {e}")
        return None

def download_logo(tmpdir):
    logo_path = os.path.join(tmpdir, 'logo.png')
    try:
        r = requests.get(LOGO_URL, timeout=10)
        with open(logo_path, 'wb') as f:
            f.write(r.content)
        return logo_path
    except:
        return None

def generate_thumbnail(title, channel, logo_path, output_path):
    try:
        W, H = 1280, 720
        theme = CHANNEL_THEMES.get(channel, CHANNEL_THEMES['news'])
        accent = theme['accent']
        bg = theme['bg']
        badge = theme['badge']

        img = Image.new('RGB', (W, H), bg)
        draw = ImageDraw.Draw(img)

        # Accent arc top-right
        for i in range(300):
            alpha = max(0, 255 - i)
            x = W - 350 + i
            draw.ellipse([x-50, -100, x+350, H//2+i], outline=(*accent,), width=2)

        # Left accent bars
        draw.rectangle([0, 0, 7, H], fill=accent)
        draw.rectangle([13, 0, 19, H], fill=(*accent[:3],))

        # Bottom accent glow
        for i in range(10):
            draw.rectangle([0, H-8-i*2, W, H-i*2], fill=accent)

        # Logo
        if logo_path and os.path.exists(logo_path):
            try:
                logo = Image.open(logo_path).convert('RGBA')
                logo = logo.resize((130, 130), Image.LANCZOS)
                img.paste(logo, (28, 18), logo)
            except Exception as e:
                print(f"[THUMB] Logo error: {e}")

        # Fonts
        try:
            font_name = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 40)
            font_sub  = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 22)
            font_badge= ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 24)
            font_big  = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 72)
            font_med  = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 54)
            font_sm   = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 42)
        except:
            font_name = font_sub = font_badge = font_big = font_med = font_sm = ImageFont.load_default()

        # DR SHEMA name
        draw.text((170, 32), "DR SHEMA", fill=(212, 175, 55), font=font_name)
        draw.text((170, 80), "Global News Studio", fill=(160, 160, 160), font=font_sub)

        # Title wrapping
        words = title.upper().split()
        lines, cur = [], []
        for w in words:
            cur.append(w)
            if len(' '.join(cur)) > 25:
                lines.append(' '.join(cur[:-1]))
                cur = [w]
        if cur:
            lines.append(' '.join(cur))
        lines = lines[:3]

        # Choose font size based on line length
        max_len = max(len(l) for l in lines)
        font_use = font_big if max_len < 18 else font_med if max_len < 24 else font_sm

        y_start = 180 if len(lines) == 1 else 155 if len(lines) == 2 else 130
        line_h = 90 if font_use == font_big else 70 if font_use == font_med else 55

        for i, line in enumerate(lines):
            y = y_start + i * line_h
            # Shadow
            draw.text((33, y+4), line, fill=(0, 0, 0), font=font_use)
            draw.text((30, y), line, fill=(255, 255, 255), font=font_use)

        # Underline accent
        uy = y_start + len(lines) * line_h + 8
        draw.rectangle([30, uy, 280, uy+6], fill=accent)

        # Badge bottom left
        bw = len(badge) * 14 + 24
        draw.rounded_rectangle([28, H-78, 28+bw, H-46], radius=6, fill=accent)
        draw.text((40, H-76), badge, fill=(255, 255, 255), font=font_badge)

        # Bottom right watermark
        draw.text((W-190, H-38), "DR SHEMA TV", fill=(120, 120, 120), font=font_sub)

        img.save(output_path, 'JPEG', quality=95)
        print(f"[THUMB] ✅ Generated: {output_path}")
        return True
    except Exception as e:
        print(f"[THUMB] Failed: {e}")
        traceback.print_exc()
        return False

async def generate_edge_tts_audio(text, output_path):
    import edge_tts
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(output_path)

def build_word_by_word_srt(script, audio_path, srt_path):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
            capture_output=True, text=True
        )
        duration = float(result.stdout.strip() or '60')
        words = script.split()
        time_per_word = duration / max(len(words), 1)

        def fmt(t):
            h,m,s,ms = int(t//3600),int((t%3600)//60),int(t%60),int((t%1)*1000)
            return f"{h:02}:{m:02}:{s:02},{ms:03}"

        with open(srt_path, 'w', encoding='utf-8') as f:
            idx = 1
            for i in range(0, len(words), 3):
                chunk = words[i:i+3]
                start = i * time_per_word
                end = (i + len(chunk)) * time_per_word
                f.write(f"{idx}\n{fmt(start)} --> {fmt(end)}\n{' '.join(chunk).upper()}\n\n")
                idx += 1
        return True
    except Exception as e:
        print(f"[SRT] Failed: {e}")
        return False

def generate_audio(script, tmpdir):
    audio_path = os.path.join(tmpdir, 'speech.mp3')
    srt_path = os.path.join(tmpdir, 'captions.srt')
    try:
        print("[TTS] Trying edge-tts...")
        asyncio.run(generate_edge_tts_audio(script, audio_path))
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
            build_word_by_word_srt(script, audio_path, srt_path)
            return audio_path, srt_path
    except Exception as e:
        print(f"[TTS] edge-tts failed: {e}")
    try:
        from gtts import gTTS
        tts = gTTS(text=script, lang='en', slow=False)
        tts.save(audio_path)
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
            build_word_by_word_srt(script, audio_path, srt_path)
            return audio_path, srt_path
    except Exception as e:
        print(f"[TTS] gtts failed: {e}")
    return None, None

def download_video(url, path):
    r = requests.get(url, stream=True, timeout=60)
    with open(path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

def loop_clip(clip_path, target_duration, output_path, idx):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', clip_path],
            capture_output=True, text=True
        )
        clip_dur = float(result.stdout.strip() or '5')
        if clip_dur >= target_duration:
            subprocess.run([
                'ffmpeg', '-y', '-i', clip_path, '-t', str(target_duration),
                '-vf', 'scale=480:270,setsar=1', '-r', '24', '-an',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', '80k', output_path
            ], capture_output=True)
        else:
            loops = int(target_duration / clip_dur) + 2
            tmp_list = output_path + '_list.txt'
            with open(tmp_list, 'w') as f:
                for _ in range(loops):
                    f.write(f"file '{clip_path}'\n")
            looped = output_path + '_looped.mp4'
            subprocess.run([
                'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                '-i', tmp_list, '-t', str(target_duration),
                '-vf', 'scale=480:270,setsar=1', '-r', '24', '-an',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', '80k', looped
            ], capture_output=True)
            if os.path.exists(looped):
                os.rename(looped, output_path)
            try: os.remove(tmp_list)
            except: pass
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        print(f"[CLIP {idx}] Error: {e}")
        return False

@app.route('/build', methods=['POST'])
def build_video():
    try:
        data = request.get_json()
        script    = data.get('script', '')
        title     = data.get('title', 'video')
        channel   = data.get('channel', 'news')
        clip1_url = data.get('clip1_url', '')
        clip2_url = data.get('clip2_url', '')
        clip3_url = data.get('clip3_url', '')

        print(f"[BUILD] {channel}: {title[:50]}")

        with tempfile.TemporaryDirectory() as tmpdir:

            # Step 1: Generate thumbnail
            logo_path = download_logo(tmpdir)
            thumb_path = os.path.join(tmpdir, 'thumbnail.jpg')
            thumb_ok = generate_thumbnail(title, channel, logo_path, thumb_path)

            # Step 2: Audio + captions
            audio_path, srt_path = generate_audio(script, tmpdir)
            has_audio = audio_path and os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000
            has_srt   = srt_path   and os.path.exists(srt_path)   and os.path.getsize(srt_path) > 10

            if not has_audio:
                return jsonify({'success': False, 'error': 'TTS failed'}), 500

            # Step 3: Duration
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
                capture_output=True, text=True
            )
            audio_duration = min(float(result.stdout.strip() or '45'), 240)

            # Step 4: Download + loop clips
            clip_urls = [u for u in [clip1_url, clip2_url, clip3_url] if u]
            clip_duration = audio_duration / max(len(clip_urls), 1)
            processed = []
            for i, url in enumerate(clip_urls):
                raw = os.path.join(tmpdir, f'raw{i}.mp4')
                out = os.path.join(tmpdir, f'proc{i}.mp4')
                try:
                    download_video(url, raw)
                    if loop_clip(raw, clip_duration, out, i):
                        processed.append(out)
                except Exception as e:
                    print(f"[BUILD] Clip {i} failed: {e}")

            if not processed:
                return jsonify({'success': False, 'error': 'No clips'}), 500

            # Step 5: Concatenate
            concat_list = os.path.join(tmpdir, 'list.txt')
            with open(concat_list, 'w') as f:
                for p in processed:
                    f.write(f"file '{p}'\n")
            concat_out = os.path.join(tmpdir, 'concat.mp4')
            subprocess.run([
                'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                '-i', concat_list, '-c', 'copy', concat_out
            ], capture_output=True)

            # Step 6: Burn captions + merge audio
            final_out = os.path.join(tmpdir, 'final.mp4')
            if has_srt:
                srt_escaped = srt_path.replace('\\', '/').replace(':', '\\:')
                vf = (f"scale=480:270,subtitles='{srt_escaped}':force_style='"
                      f"FontName=Arial,FontSize=16,Bold=1,"
                      f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                      f"Outline=2,Shadow=1,Alignment=2,MarginV=15'")
                r = subprocess.run([
                    'ffmpeg', '-y', '-i', concat_out, '-i', audio_path,
                    '-map', '0:v:0', '-map', '1:a:0', '-vf', vf,
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', '100k',
                    '-c:a', 'aac', '-b:a', '48k', '-shortest', final_out
                ], capture_output=True, timeout=300)
                if r.returncode != 0:
                    subprocess.run([
                        'ffmpeg', '-y', '-i', concat_out, '-i', audio_path,
                        '-map', '0:v:0', '-map', '1:a:0',
                        '-c:v', 'libx264', '-preset', 'ultrafast',
                        '-b:v', '80k', '-vf', 'scale=480:270',
                        '-c:a', 'aac', '-b:a', '48k', '-shortest', final_out
                    ], capture_output=True)
            else:
                subprocess.run([
                    'ffmpeg', '-y', '-i', concat_out, '-i', audio_path,
                    '-map', '0:v:0', '-map', '1:a:0',
                    '-c:v', 'libx264', '-preset', 'ultrafast',
                    '-b:v', '80k', '-vf', 'scale=480:270',
                    '-c:a', 'aac', '-b:a', '48k', '-shortest', final_out
                ], capture_output=True)

            if not os.path.exists(final_out) or os.path.getsize(final_out) == 0:
                return jsonify({'success': False, 'error': 'Final video failed'}), 500

            file_size = os.path.getsize(final_out)
            print(f"[BUILD] Final: {file_size} bytes")

            # Step 7: Upload video + thumbnail to Google Drive
            drive_video_id = upload_to_drive(final_out, title, 'video/mp4')
            drive_thumb_id = None
            if thumb_ok and os.path.exists(thumb_path):
                drive_thumb_id = upload_to_drive(thumb_path, f"{title}_thumbnail", 'image/jpeg')

            if drive_video_id:
                return jsonify({
                    'success': True,
                    'has_audio': True,
                    'has_captions': has_srt,
                    'has_thumbnail': drive_thumb_id is not None,
                    'file_size': file_size,
                    'duration': round(audio_duration, 1),
                    'title': title,
                    'drive_video_id': drive_video_id,
                    'drive_thumb_id': drive_thumb_id,
                    'direct_upload': True,
                    'video': ''
                })
            else:
                with open(final_out, 'rb') as f:
                    video_b64 = base64.b64encode(f.read()).decode('utf-8')
                return jsonify({
                    'success': True,
                    'has_audio': True,
                    'has_captions': has_srt,
                    'has_thumbnail': False,
                    'file_size': file_size,
                    'title': title,
                    'video': video_b64
                })

    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'voice': VOICE, 'thumbnails': True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

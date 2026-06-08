from flask import Flask, request, jsonify
import subprocess
import tempfile
import os
import requests
import asyncio
import traceback
import base64
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = Flask(__name__)

VOICE = "en-US-ChristopherNeural"
GDRIVE_FOLDER_ID = "1yGoGX3f9zrsK_uJjcgOjugngu0x5TDsA"

def get_drive_service():
    creds_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if not creds_json:
        return None
    try:
        creds_dict = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=['https://www.googleapis.com/auth/drive.file']
        )
        return build('drive', 'v3', credentials=credentials)
    except Exception as e:
        print(f"[DRIVE] Auth failed: {e}")
        return None

def upload_to_drive(file_path, title, mime_type='video/mp4'):
    try:
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
            body=file_metadata,
            media_body=media,
            fields='id,name'
        ).execute()
        print(f"[DRIVE] ✅ Uploaded: {file['name']} → {file['id']}")
        return file['id']
    except Exception as e:
        print(f"[DRIVE] Upload failed: {e}")
        return None

async def generate_edge_tts_audio(text, output_path):
    import edge_tts
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(output_path)

def build_srt(script, audio_path, srt_path):
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
        asyncio.run(generate_edge_tts_audio(script, audio_path))
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
            build_srt(script, audio_path, srt_path)
            return audio_path, srt_path
    except Exception as e:
        print(f"[TTS] edge-tts failed: {e}")
    try:
        from gtts import gTTS
        tts = gTTS(text=script, lang='en', slow=False)
        tts.save(audio_path)
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
            build_srt(script, audio_path, srt_path)
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
                'ffmpeg', '-y', '-i', clip_path,
                '-t', str(target_duration),
                '-vf', 'scale=640:360,setsar=1', '-r', '25', '-an',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', '300k', output_path
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
                '-vf', 'scale=640:360,setsar=1', '-r', '25', '-an',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-b:v', '300k', looped
            ], capture_output=True)
            if os.path.exists(looped):
                os.rename(looped, output_path)
            try: os.remove(tmp_list)
            except: pass
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        print(f"[CLIP {idx}] Error: {e}")
        return False

def generate_thumbnail(video_path, title, output_path):
    try:
        frame_path = output_path + '_frame.jpg'
        subprocess.run([
            'ffmpeg', '-y', '-i', video_path,
            '-ss', '3', '-vframes', '1',
            '-vf', 'scale=640:360', frame_path
        ], capture_output=True)
        if not os.path.exists(frame_path) or os.path.getsize(frame_path) == 0:
            return None
        safe_title = title[:50].replace("'","").replace('"','').replace(':','-')
        r = subprocess.run([
            'ffmpeg', '-y', '-i', frame_path,
            '-vf',
            f"drawbox=x=0:y=ih-70:w=iw:h=70:color=black@0.7:t=fill,"
            f"drawtext=text='DR SHEMA':fontcolor=yellow:fontsize=20:x=10:y=h-60,"
            f"drawtext=text='{safe_title}':fontcolor=white:fontsize=14:x=10:y=h-35",
            output_path
        ], capture_output=True)
        if r.returncode != 0:
            import shutil
            shutil.copy(frame_path, output_path)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"[THUMB] ✅ {os.path.getsize(output_path)} bytes")
            return output_path
        return None
    except Exception as e:
        print(f"[THUMB] Failed: {e}")
        return None

@app.route('/build', methods=['POST'])
def build_video():
    try:
        data = request.get_json()
        script = data.get('script', '')
        title = data.get('title', 'video')
        clip1_url = data.get('clip1_url', '')
        clip2_url = data.get('clip2_url', '')
        clip3_url = data.get('clip3_url', '')

        print(f"[BUILD] Starting: {title[:60]}")

        with tempfile.TemporaryDirectory() as tmpdir:
            # Audio
            audio_path, srt_path = generate_audio(script, tmpdir)
            if not audio_path:
                return jsonify({'success': False, 'error': 'TTS failed'}), 500

            has_srt = srt_path and os.path.exists(srt_path) and os.path.getsize(srt_path) > 10

            # Duration
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
                capture_output=True, text=True
            )
            audio_duration = min(float(result.stdout.strip() or '45'), 240)
            print(f"[BUILD] Duration: {audio_duration:.1f}s")

            # Clips
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
                    print(f"[CLIP {i}] failed: {e}")

            if not processed:
                return jsonify({'success': False, 'error': 'No clips'}), 500

            # Concat
            concat_list = os.path.join(tmpdir, 'list.txt')
            with open(concat_list, 'w') as f:
                for p in processed:
                    f.write(f"file '{p}'\n")
            concat_out = os.path.join(tmpdir, 'concat.mp4')
            subprocess.run([
                'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                '-i', concat_list, '-c', 'copy', concat_out
            ], capture_output=True)

            # Final with captions
            final_out = os.path.join(tmpdir, 'final.mp4')
            if has_srt:
                srt_escaped = srt_path.replace('\\', '/').replace(':', '\\:')
                vf = (f"scale=640:360,subtitles='{srt_escaped}':force_style='"
                      f"FontName=Arial,FontSize=18,Bold=1,"
                      f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                      f"Outline=2,Shadow=1,Alignment=2,MarginV=20'")
                r = subprocess.run([
                    'ffmpeg', '-y', '-i', concat_out, '-i', audio_path,
                    '-map', '0:v:0', '-map', '1:a:0', '-vf', vf,
                    '-c:v', 'libx264', '-preset', 'fast', '-b:v', '500k',
                    '-c:a', 'aac', '-b:a', '96k', '-shortest', final_out
                ], capture_output=True, timeout=300)
                if r.returncode != 0:
                    subprocess.run([
                        'ffmpeg', '-y', '-i', concat_out, '-i', audio_path,
                        '-map', '0:v:0', '-map', '1:a:0',
                        '-c:v', 'libx264', '-preset', 'fast', '-b:v', '500k',
                        '-vf', 'scale=640:360', '-c:a', 'aac', '-b:a', '96k',
                        '-shortest', final_out
                    ], capture_output=True)
            else:
                subprocess.run([
                    'ffmpeg', '-y', '-i', concat_out, '-i', audio_path,
                    '-map', '0:v:0', '-map', '1:a:0',
                    '-c:v', 'libx264', '-preset', 'fast', '-b:v', '500k',
                    '-vf', 'scale=640:360', '-c:a', 'aac', '-b:a', '96k',
                    '-shortest', final_out
                ], capture_output=True)

            if not os.path.exists(final_out) or os.path.getsize(final_out) == 0:
                return jsonify({'success': False, 'error': 'Final video failed'}), 500

            file_size = os.path.getsize(final_out)
            print(f"[BUILD] Final: {file_size/1024/1024:.1f}MB")

            # Thumbnail
            thumbnail_path = os.path.join(tmpdir, 'thumbnail.jpg')
            thumb_result = generate_thumbnail(final_out, title, thumbnail_path)
            has_thumbnail = thumb_result is not None

            # Try direct Drive upload
            drive_video_id = upload_to_drive(final_out, title, 'video/mp4')
            drive_thumb_id = None
            if has_thumbnail:
                drive_thumb_id = upload_to_drive(thumbnail_path, f"{title}_thumb", 'image/jpeg')

            if drive_video_id:
                print(f"[BUILD] ✅ Direct Drive: {drive_video_id}")
                return jsonify({
                    'success': True,
                    'has_audio': True,
                    'has_captions': has_srt,
                    'has_thumbnail': has_thumbnail,
                    'file_size': file_size,
                    'duration': round(audio_duration, 1),
                    'title': title,
                    'drive_file_id': drive_video_id,
                    'drive_thumb_id': drive_thumb_id,
                    'direct_upload': True,
                    'video': '',
                    'thumbnail': ''
                })
            else:
                # Fallback base64
                with open(final_out, 'rb') as f:
                    video_b64 = base64.b64encode(f.read()).decode('utf-8')
                return jsonify({
                    'success': True,
                    'has_audio': True,
                    'has_captions': has_srt,
                    'has_thumbnail': has_thumbnail,
                    'file_size': file_size,
                    'duration': round(audio_duration, 1),
                    'title': title,
                    'drive_file_id': None,
                    'direct_upload': False,
                    'video': video_b64,
                    'thumbnail': ''
                })

    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    has_creds = bool(os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON'))
    return jsonify({'status': 'ok', 'voice': VOICE, 'quality': '640x360', 'direct_drive': has_creds})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

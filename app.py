from flask import Flask, request, jsonify
import subprocess
import tempfile
import os
import requests
import asyncio
import traceback
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

app = Flask(__name__)

VOICE = "en-US-ChristopherNeural"
GDRIVE_FOLDER_ID = "1yGoGX3f9zrsK_uJjcgOjugngu0x5TDsA"

def get_drive_service():
    """Get Google Drive service using service account"""
    creds_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if not creds_json:
        return None
    creds_dict = json.loads(creds_json)
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=['https://www.googleapis.com/auth/drive.file']
    )
    return build('drive', 'v3', credentials=credentials)

def upload_to_drive(file_path, title):
    """Upload file directly to Google Drive as native MP4"""
    try:
        service = get_drive_service()
        if not service:
            print("[DRIVE] No service account — skipping direct upload")
            return None
        
        file_metadata = {
            'name': f"{title}.mp4",
            'parents': [GDRIVE_FOLDER_ID],
            'mimeType': 'video/mp4'
        }
        media = MediaFileUpload(
            file_path,
            mimetype='video/mp4',
            resumable=True
        )
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id,webViewLink,name'
        ).execute()
        
        # Make file accessible
        service.permissions().create(
            fileId=file['id'],
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()
        
        print(f"[DRIVE] ✅ Uploaded: {file['name']} → {file['id']}")
        return file['id']
    except Exception as e:
        print(f"[DRIVE] Upload failed: {e}")
        traceback.print_exc()
        return None

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

        chunk_size = 3
        with open(srt_path, 'w', encoding='utf-8') as f:
            idx = 1
            for i in range(0, len(words), chunk_size):
                chunk = words[i:i+chunk_size]
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
            print(f"[TTS] edge-tts SUCCESS: {os.path.getsize(audio_path)} bytes")
            build_word_by_word_srt(script, audio_path, srt_path)
            return audio_path, srt_path
    except Exception as e:
        print(f"[TTS] edge-tts FAILED: {e}")

    try:
        print("[TTS] Trying gtts...")
        from gtts import gTTS
        tts = gTTS(text=script, lang='en', slow=False)
        tts.save(audio_path)
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
            build_word_by_word_srt(script, audio_path, srt_path)
            return audio_path, srt_path
    except Exception as e:
        print(f"[TTS] gtts FAILED: {e}")

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
            try:
                os.remove(tmp_list)
            except:
                pass

        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        print(f"[CLIP {idx}] Error: {e}")
        return False

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

            # Step 1: Audio + captions
            audio_path, srt_path = generate_audio(script, tmpdir)
            has_audio = audio_path and os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000
            has_srt = srt_path and os.path.exists(srt_path) and os.path.getsize(srt_path) > 10

            if not has_audio:
                return jsonify({'success': False, 'error': 'TTS failed'}), 500

            # Step 2: Duration
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
                capture_output=True, text=True
            )
            audio_duration = float(result.stdout.strip() or '45')
            audio_duration = min(audio_duration, 240)

            # Step 3: Download + loop clips
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

            # Step 4: Concatenate
            concat_list = os.path.join(tmpdir, 'list.txt')
            with open(concat_list, 'w') as f:
                for p in processed:
                    f.write(f"file '{p}'\n")

            concat_out = os.path.join(tmpdir, 'concat.mp4')
            subprocess.run([
                'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                '-i', concat_list, '-c', 'copy', concat_out
            ], capture_output=True)

            # Step 5: Burn captions + merge audio
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

            # Step 6: Try direct Google Drive upload
            drive_file_id = upload_to_drive(final_out, title)

            if drive_file_id:
                # Direct upload succeeded — return file ID only, no base64
                print(f"[BUILD] ✅ Direct Drive upload: {drive_file_id}")
                return jsonify({
                    'success': True,
                    'has_audio': True,
                    'has_captions': has_srt,
                    'file_size': file_size,
                    'duration': round(audio_duration, 1),
                    'title': title,
                    'drive_file_id': drive_file_id,
                    'direct_upload': True,
                    'video': ''  # No base64 needed
                })
            else:
                # Fallback: return base64 for n8n to upload
                with open(final_out, 'rb') as f:
                    video_bytes = f.read()
                import base64
                video_b64 = base64.b64encode(video_bytes).decode('utf-8')
                return jsonify({
                    'success': True,
                    'has_audio': True,
                    'has_captions': has_srt,
                    'file_size': file_size,
                    'duration': round(audio_duration, 1),
                    'title': title,
                    'drive_file_id': None,
                    'direct_upload': False,
                    'video': video_b64
                })

    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    has_creds = bool(os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON'))
    return jsonify({'status': 'ok', 'voice': VOICE, 'direct_drive': has_creds})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

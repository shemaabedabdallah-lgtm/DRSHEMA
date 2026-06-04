from flask import Flask, request, jsonify
import subprocess
import tempfile
import os
import requests
import asyncio
import traceback
import math

app = Flask(__name__)

VOICE = "en-US-ChristopherNeural"

async def generate_edge_tts(text, output_path, srt_path):
    import edge_tts
    communicate = edge_tts.Communicate(text, VOICE)
    words = []
    async for event in communicate.stream():
        if event["type"] == "WordBoundary":
            words.append({
                "word": event["text"],
                "start": event["offset"] / 10_000_000,
                "duration": event["duration"] / 10_000_000
            })
    # Save audio separately
    communicate2 = edge_tts.Communicate(text, VOICE)
    await communicate2.save(output_path)
    # Build SRT from word timings
    build_srt(words, srt_path)

def build_srt(words, srt_path):
    """Group words into subtitle lines of ~6 words each"""
    if not words:
        return
    lines = []
    chunk = []
    chunk_start = None
    for w in words:
        if chunk_start is None:
            chunk_start = w["start"]
        chunk.append(w["word"])
        if len(chunk) >= 6:
            end = w["start"] + w["duration"]
            lines.append((chunk_start, end, " ".join(chunk)))
            chunk = []
            chunk_start = None
    if chunk:
        end = words[-1]["start"] + words[-1]["duration"]
        lines.append((chunk_start, end, " ".join(chunk)))

    def fmt_time(t):
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        ms = int((t % 1) * 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    with open(srt_path, 'w', encoding='utf-8') as f:
        for i, (start, end, text) in enumerate(lines, 1):
            f.write(f"{i}\n{fmt_time(start)} --> {fmt_time(end)}\n{text}\n\n")

def generate_audio(script, tmpdir):
    audio_path = os.path.join(tmpdir, 'speech.mp3')
    srt_path = os.path.join(tmpdir, 'captions.srt')

    # Method 1: edge-tts with word timings
    try:
        print("[TTS] Trying edge-tts...")
        asyncio.run(generate_edge_tts(script, audio_path, srt_path))
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
            print(f"[TTS] edge-tts SUCCESS: {os.path.getsize(audio_path)} bytes")
            return audio_path, srt_path
        else:
            print("[TTS] edge-tts produced empty file")
    except Exception as e:
        print(f"[TTS] edge-tts FAILED: {e}")
        traceback.print_exc()

    # Method 2: gtts (no word timings, generate basic SRT)
    try:
        print("[TTS] Trying gtts...")
        from gtts import gTTS
        tts = gTTS(text=script, lang='en', slow=False)
        tts.save(audio_path)
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
            print(f"[TTS] gtts SUCCESS: {os.path.getsize(audio_path)} bytes")
            build_basic_srt(script, audio_path, srt_path)
            return audio_path, srt_path
    except Exception as e:
        print(f"[TTS] gtts FAILED: {e}")

    # Method 3: espeak
    try:
        print("[TTS] Trying espeak...")
        wav_path = os.path.join(tmpdir, 'speech.wav')
        subprocess.run(
            ['espeak', '-v', 'en-us+m3', '-s', '145', '-p', '35',
             '-w', wav_path, script[:2000]],
            capture_output=True, timeout=60
        )
        if os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000:
            subprocess.run(['ffmpeg', '-y', '-i', wav_path, audio_path], capture_output=True)
            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
                build_basic_srt(script, audio_path, srt_path)
                return audio_path, srt_path
    except Exception as e:
        print(f"[TTS] espeak FAILED: {e}")

    return None, None

def build_basic_srt(script, audio_path, srt_path):
    """Estimate timing when word-level data unavailable"""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
            capture_output=True, text=True
        )
        duration = float(result.stdout.strip() or '60')
        words = script.split()
        chunk_size = 6
        chunks = [words[i:i+chunk_size] for i in range(0, len(words), chunk_size)]
        time_per_chunk = duration / max(len(chunks), 1)

        def fmt_time(t):
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            s = int(t % 60)
            ms = int((t % 1) * 1000)
            return f"{h:02}:{m:02}:{s:02},{ms:03}"

        with open(srt_path, 'w', encoding='utf-8') as f:
            for i, chunk in enumerate(chunks):
                start = i * time_per_chunk
                end = start + time_per_chunk
                f.write(f"{i+1}\n{fmt_time(start)} --> {fmt_time(end)}\n{' '.join(chunk)}\n\n")
    except Exception as e:
        print(f"[SRT] basic SRT failed: {e}")

def download_video(url, path):
    r = requests.get(url, stream=True, timeout=30)
    with open(path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

@app.route('/build', methods=['POST'])
def build_video():
    try:
        data = request.get_json()
        script = data.get('script', '')
        title = data.get('title', 'video')
        clip1_url = data.get('clip1_url', '')
        clip2_url = data.get('clip2_url', '')
        clip3_url = data.get('clip3_url', '')

        print(f"[BUILD] Starting: {title[:50]}")

        with tempfile.TemporaryDirectory() as tmpdir:

            # Step 1: Generate audio + SRT captions
            audio_path, srt_path = generate_audio(script, tmpdir)
            has_audio = audio_path and os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000

            if not has_audio:
                return jsonify({'success': False, 'error': 'All TTS methods failed', 'has_audio': False}), 500

            has_srt = srt_path and os.path.exists(srt_path) and os.path.getsize(srt_path) > 10
            print(f"[BUILD] has_audio={has_audio}, has_srt={has_srt}")

            # Step 2: Audio duration
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
                capture_output=True, text=True
            )
            audio_duration = float(result.stdout.strip() or '45')
            audio_duration = min(audio_duration, 480)

            # Step 3: Download clips
            clip_paths = []
            for i, url in enumerate([clip1_url, clip2_url, clip3_url]):
                if url:
                    p = os.path.join(tmpdir, f'clip{i}.mp4')
                    try:
                        download_video(url, p)
                        clip_paths.append(p)
                    except Exception as e:
                        print(f"[BUILD] Clip {i} failed: {e}")

            if not clip_paths:
                return jsonify({'success': False, 'error': 'No clips downloaded'}), 500

            # Step 4: Trim clips
            clip_duration = audio_duration / len(clip_paths)
            trimmed = []
            for i, cp in enumerate(clip_paths):
                out = os.path.join(tmpdir, f'trimmed{i}.mp4')
                subprocess.run([
                    'ffmpeg', '-y', '-i', cp,
                    '-t', str(clip_duration),
                    '-vf', 'scale=640:360,setsar=1',
                    '-r', '25', '-an',
                    '-c:v', 'libx264', '-preset', 'ultrafast',
                    '-b:v', '150k', out
                ], capture_output=True)
                if os.path.exists(out):
                    trimmed.append(out)

            # Step 5: Concatenate
            concat_list = os.path.join(tmpdir, 'list.txt')
            with open(concat_list, 'w') as f:
                for t in trimmed:
                    f.write(f"file '{t}'\n")

            concat_out = os.path.join(tmpdir, 'concat.mp4')
            subprocess.run([
                'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                '-i', concat_list, '-c', 'copy', concat_out
            ], capture_output=True)

            # Step 6: Burn captions + merge audio
            final_out = os.path.join(tmpdir, 'final.mp4')

            if has_srt:
                # Escape srt path for ffmpeg filter
                srt_escaped = srt_path.replace(':', '\\:').replace("'", "\\'")
                vf = (
                    f"scale=640:360,"
                    f"subtitles='{srt_escaped}':force_style='"
                    f"FontName=Arial,FontSize=16,Bold=1,"
                    f"PrimaryColour=&HFFFFFF,OutlineColour=&H000000,"
                    f"Outline=2,Shadow=1,Alignment=2,"
                    f"MarginV=20'"
                )
                r = subprocess.run([
                    'ffmpeg', '-y',
                    '-i', concat_out,
                    '-i', audio_path,
                    '-map', '0:v:0', '-map', '1:a:0',
                    '-vf', vf,
                    '-c:v', 'libx264', '-preset', 'ultrafast',
                    '-b:v', '300k',
                    '-c:a', 'aac', '-b:a', '64k',
                    '-shortest', final_out
                ], capture_output=True, timeout=300)
                print(f"[BUILD] FFmpeg captions stderr: {r.stderr.decode()[-300:]}")
            else:
                # No captions — just merge
                subprocess.run([
                    'ffmpeg', '-y',
                    '-i', concat_out, '-i', audio_path,
                    '-map', '0:v:0', '-map', '1:a:0',
                    '-c:v', 'libx264', '-preset', 'ultrafast',
                    '-b:v', '150k', '-vf', 'scale=640:360',
                    '-c:a', 'aac', '-b:a', '64k',
                    '-shortest', final_out
                ], capture_output=True)

            if not os.path.exists(final_out) or os.path.getsize(final_out) == 0:
                return jsonify({'success': False, 'error': 'Final video failed'}), 500

            print(f"[BUILD] Final: {os.path.getsize(final_out)} bytes")

            with open(final_out, 'rb') as f:
                video_bytes = f.read()

            import base64
            video_b64 = base64.b64encode(video_bytes).decode('utf-8')

            return jsonify({
                'success': True,
                'has_audio': True,
                'has_captions': has_srt,
                'title': title,
                'video': video_b64
            })

    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'voice': VOICE, 'captions': True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

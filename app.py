from flask import Flask, request, jsonify
import subprocess
import tempfile
import os
import requests
import asyncio
import traceback

app = Flask(__name__)

VOICE = "en-US-ChristopherNeural"

async def generate_edge_tts_audio(text, output_path):
    import edge_tts
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(output_path)

def build_word_by_word_srt(script, audio_path, srt_path):
    """Build word-by-word karaoke style SRT"""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
            capture_output=True, text=True
        )
        duration = float(result.stdout.strip() or '60')
        words = script.split()
        total_words = len(words)
        time_per_word = duration / max(total_words, 1)

        def fmt_time(t):
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            s = int(t % 60)
            ms = int((t % 1) * 1000)
            return f"{h:02}:{m:02}:{s:02},{ms:03}"

        # Group into lines of 3 words for readability
        chunk_size = 3
        chunks = []
        for i in range(0, total_words, chunk_size):
            chunk_words = words[i:i+chunk_size]
            start_time = i * time_per_word
            end_time = (i + len(chunk_words)) * time_per_word
            chunks.append((start_time, end_time, ' '.join(chunk_words).upper()))

        with open(srt_path, 'w', encoding='utf-8') as f:
            for i, (start, end, text) in enumerate(chunks, 1):
                f.write(f"{i}\n{fmt_time(start)} --> {fmt_time(end)}\n{text}\n\n")

        print(f"[SRT] Built {len(chunks)} word-by-word chunks over {duration:.1f}s")
        return True
    except Exception as e:
        print(f"[SRT] Failed: {e}")
        return False

def generate_audio(script, tmpdir):
    audio_path = os.path.join(tmpdir, 'speech.mp3')
    srt_path = os.path.join(tmpdir, 'captions.srt')

    # Method 1: edge-tts
    try:
        print("[TTS] Trying edge-tts...")
        asyncio.run(generate_edge_tts_audio(script, audio_path))
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
            print(f"[TTS] edge-tts SUCCESS: {os.path.getsize(audio_path)} bytes")
            build_word_by_word_srt(script, audio_path, srt_path)
            return audio_path, srt_path
    except Exception as e:
        print(f"[TTS] edge-tts FAILED: {e}")
        traceback.print_exc()

    # Method 2: gtts
    try:
        print("[TTS] Trying gtts...")
        from gtts import gTTS
        tts = gTTS(text=script, lang='en', slow=False)
        tts.save(audio_path)
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
            print(f"[TTS] gtts SUCCESS")
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

def loop_clip_to_duration(clip_path, target_duration, output_path, clip_index):
    """Loop a short clip to fill target duration"""
    try:
        # Get clip duration
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', clip_path],
            capture_output=True, text=True
        )
        clip_dur = float(result.stdout.strip() or '5')
        print(f"[CLIP {clip_index}] Original duration: {clip_dur:.1f}s, need: {target_duration:.1f}s")

        if clip_dur >= target_duration:
            # Clip is long enough, just trim it
            subprocess.run([
                'ffmpeg', '-y', '-i', clip_path,
                '-t', str(target_duration),
                '-vf', 'scale=640:360,setsar=1',
                '-r', '25', '-an',
                '-c:v', 'libx264', '-preset', 'ultrafast',
                '-b:v', '200k', output_path
            ], capture_output=True)
        else:
            # Loop clip to fill duration
            loops_needed = int(target_duration / clip_dur) + 2
            # Create concat list with loops
            tmp_list = output_path + '_list.txt'
            with open(tmp_list, 'w') as f:
                for _ in range(loops_needed):
                    f.write(f"file '{clip_path}'\n")
            
            looped = output_path + '_looped.mp4'
            subprocess.run([
                'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                '-i', tmp_list, '-t', str(target_duration),
                '-vf', 'scale=640:360,setsar=1',
                '-r', '25', '-an',
                '-c:v', 'libx264', '-preset', 'ultrafast',
                '-b:v', '200k', looped
            ], capture_output=True)
            
            os.rename(looped, output_path)
            try:
                os.remove(tmp_list)
            except:
                pass

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"[CLIP {clip_index}] Processed successfully")
            return True
        return False
    except Exception as e:
        print(f"[CLIP {clip_index}] Processing failed: {e}")
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
        print(f"[BUILD] Script length: {len(script)} chars")

        with tempfile.TemporaryDirectory() as tmpdir:

            # Step 1: Generate audio + word-by-word captions
            audio_path, srt_path = generate_audio(script, tmpdir)
            has_audio = audio_path and os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000
            has_srt = srt_path and os.path.exists(srt_path) and os.path.getsize(srt_path) > 10

            if not has_audio:
                return jsonify({'success': False, 'error': 'All TTS methods failed'}), 500

            # Step 2: Get FULL audio duration
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
                capture_output=True, text=True
            )
            audio_duration = float(result.stdout.strip() or '45')
            audio_duration = min(audio_duration, 480)
            print(f"[BUILD] Full audio duration: {audio_duration:.1f}s")

            # Step 3: Download clips
            clip_urls = [u for u in [clip1_url, clip2_url, clip3_url] if u]
            raw_clips = []
            for i, url in enumerate(clip_urls):
                p = os.path.join(tmpdir, f'raw_clip{i}.mp4')
                try:
                    download_video(url, p)
                    raw_clips.append(p)
                    size = os.path.getsize(p)
                    print(f"[BUILD] Raw clip {i}: {size} bytes")
                except Exception as e:
                    print(f"[BUILD] Clip {i} download failed: {e}")

            if not raw_clips:
                return jsonify({'success': False, 'error': 'No clips downloaded'}), 500

            # Step 4: Process each clip — loop short clips to fill their share of duration
            clip_duration = audio_duration / len(raw_clips)
            processed_clips = []
            for i, rp in enumerate(raw_clips):
                out = os.path.join(tmpdir, f'proc_clip{i}.mp4')
                success = loop_clip_to_duration(rp, clip_duration, out, i)
                if success:
                    processed_clips.append(out)

            if not processed_clips:
                return jsonify({'success': False, 'error': 'No clips processed'}), 500

            # Step 5: Concatenate all processed clips
            concat_list = os.path.join(tmpdir, 'concat_list.txt')
            with open(concat_list, 'w') as f:
                for cp in processed_clips:
                    f.write(f"file '{cp}'\n")

            concat_out = os.path.join(tmpdir, 'concat.mp4')
            subprocess.run([
                'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                '-i', concat_list, '-c', 'copy', concat_out
            ], capture_output=True)

            # Step 6: Burn word-by-word captions + merge audio
            final_out = os.path.join(tmpdir, 'final.mp4')

            if has_srt:
                srt_escaped = srt_path.replace('\\', '/').replace(':', '\\:')
                # Bold white word-by-word captions
                vf = (
                    f"scale=640:360,"
                    f"subtitles='{srt_escaped}':force_style='"
                    f"FontName=Arial,"
                    f"FontSize=20,"
                    f"Bold=1,"
                    f"PrimaryColour=&H00FFFFFF,"
                    f"OutlineColour=&H00000000,"
                    f"BackColour=&H80000000,"
                    f"Outline=3,"
                    f"Shadow=2,"
                    f"Alignment=2,"
                    f"MarginV=25'"
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
                print(f"[BUILD] FFmpeg captions returncode: {r.returncode}")
                if r.returncode != 0:
                    print(f"[BUILD] Caption error, falling back: {r.stderr.decode()[-200:]}")
                    subprocess.run([
                        'ffmpeg', '-y',
                        '-i', concat_out, '-i', audio_path,
                        '-map', '0:v:0', '-map', '1:a:0',
                        '-c:v', 'libx264', '-preset', 'ultrafast',
                        '-b:v', '200k', '-vf', 'scale=640:360',
                        '-c:a', 'aac', '-b:a', '64k',
                        '-shortest', final_out
                    ], capture_output=True)
            else:
                subprocess.run([
                    'ffmpeg', '-y',
                    '-i', concat_out, '-i', audio_path,
                    '-map', '0:v:0', '-map', '1:a:0',
                    '-c:v', 'libx264', '-preset', 'ultrafast',
                    '-b:v', '200k', '-vf', 'scale=640:360',
                    '-c:a', 'aac', '-b:a', '64k',
                    '-shortest', final_out
                ], capture_output=True)

            if not os.path.exists(final_out) or os.path.getsize(final_out) == 0:
                return jsonify({'success': False, 'error': 'Final video failed'}), 500

            file_size = os.path.getsize(final_out)
            print(f"[BUILD] ✅ Final: {file_size} bytes, duration ~{audio_duration:.1f}s")

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
                'video': video_b64
            })

    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'voice': VOICE, 'captions': 'word_by_word'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

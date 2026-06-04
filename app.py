from flask import Flask, request, jsonify
import subprocess
import tempfile
import os
import requests
import asyncio
import edge_tts

app = Flask(__name__)

VOICE = "en-US-ChristopherNeural"  # Deep professional male voice

async def generate_audio(text, output_path):
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(output_path)

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

        with tempfile.TemporaryDirectory() as tmpdir:

            # Step 1: Generate male audio with edge-tts
            audio_path = os.path.join(tmpdir, 'speech.mp3')
            asyncio.run(generate_audio(script, audio_path))

            if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
                return jsonify({'success': False, 'error': 'Audio generation failed'}), 500

            # Step 2: Get audio duration
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
                capture_output=True, text=True
            )
            audio_duration = float(result.stdout.strip() or '45')
            audio_duration = min(audio_duration, 480)  # Max 8 minutes

            # Step 3: Download video clips
            clip_paths = []
            for i, url in enumerate([clip1_url, clip2_url, clip3_url]):
                if url:
                    p = os.path.join(tmpdir, f'clip{i}.mp4')
                    download_video(url, p)
                    clip_paths.append(p)

            if not clip_paths:
                return jsonify({'success': False, 'error': 'No video clips'}), 500

            # Step 4: Build looped video to match audio duration
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
                trimmed.append(out)

            # Step 5: Concatenate clips
            concat_list = os.path.join(tmpdir, 'list.txt')
            with open(concat_list, 'w') as f:
                for t in trimmed:
                    f.write(f"file '{t}'\n")

            concat_out = os.path.join(tmpdir, 'concat.mp4')
            subprocess.run([
                'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                '-i', concat_list, '-c', 'copy', concat_out
            ], capture_output=True)

            # Step 6: Merge video + audio
            final_out = os.path.join(tmpdir, 'final.mp4')
            subprocess.run([
                'ffmpeg', '-y',
                '-i', concat_out,
                '-i', audio_path,
                '-map', '0:v:0', '-map', '1:a:0',
                '-c:v', 'libx264', '-preset', 'ultrafast',
                '-b:v', '150k', '-vf', 'scale=640:360',
                '-c:a', 'aac', '-b:a', '64k',
                '-shortest', final_out
            ], capture_output=True)

            if not os.path.exists(final_out) or os.path.getsize(final_out) == 0:
                return jsonify({'success': False, 'error': 'Final video build failed'}), 500

            # Step 7: Read and return video
            with open(final_out, 'rb') as f:
                video_bytes = f.read()

            import base64
            video_b64 = base64.b64encode(video_bytes).decode('utf-8')

            return jsonify({
                'success': True,
                'has_audio': True,
                'title': title,
                'video': video_b64
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'voice': VOICE})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

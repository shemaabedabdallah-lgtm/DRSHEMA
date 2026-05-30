#!/usr/bin/env python3
"""
DR SHEMA Video Builder Service
Deployed on Render.com
Receives job from n8n, builds video with flite voice + Pexels clips + DR SHEMA watermark
Returns finished video as base64
"""

from flask import Flask, request, jsonify
import subprocess, os, tempfile, urllib.request, base64, json, re

app = Flask(__name__)

LOGO_PATH = "/app/logo.png"

def download_clip(url, dest):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as r, open(dest, 'wb') as f:
            f.write(r.read())
        return os.path.getsize(dest) > 1000
    except Exception as e:
        print(f"Download failed {url}: {e}")
        return False

def build_video(data):
    tmp = tempfile.mkdtemp(prefix='drshema_')
    clips = []

    # Download Pexels clips
    for i, url in enumerate([data.get('clip1_url',''), data.get('clip2_url',''), data.get('clip3_url','')]):
        if not url:
            continue
        dest = os.path.join(tmp, f'clip_{i}.mp4')
        print(f"Downloading clip {i+1}...")
        if download_clip(url, dest):
            clips.append(dest)

    # Generate voice with flite
    script = data.get('script', '')
    script = re.sub(r"[^\w\s.,!?-]", ' ', script)[:3000]
    script_file = os.path.join(tmp, 'script.txt')
    audio_wav = os.path.join(tmp, 'audio.wav')
    audio_mp3 = os.path.join(tmp, 'audio.mp3')

    with open(script_file, 'w') as f:
        f.write(script)

    has_audio = False
    try:
        subprocess.run(['flite', '-voice', 'rms', '-f', script_file, '-o', audio_wav],
                      timeout=120, check=True, capture_output=True)
        subprocess.run(['ffmpeg', '-i', audio_wav, '-codec:a', 'libmp3lame',
                       '-qscale:a', '2', audio_mp3, '-y'],
                      timeout=30, check=True, capture_output=True)
        has_audio = os.path.exists(audio_mp3) and os.path.getsize(audio_mp3) > 100
        print(f"Voice generated: {os.path.getsize(audio_mp3)} bytes")
    except Exception as e:
        print(f"Voice generation error: {e}")

    # Fallback background if no clips
    if not clips:
        print("No clips - using dark background")
        fb = os.path.join(tmp, 'fallback.mp4')
        subprocess.run([
            'ffmpeg', '-f', 'lavfi',
            '-i', 'color=c=0x0a0a1a:size=1920x1080:duration=60',
            '-c:v', 'libx264', '-t', '60', fb, '-y'
        ], capture_output=True)
        if os.path.exists(fb):
            clips.append(fb)

    # Trim each clip to 12 seconds
    trimmed = []
    for i, clip in enumerate(clips):
        out = os.path.join(tmp, f'trim_{i}.mp4')
        subprocess.run([
            'ffmpeg', '-i', clip, '-t', '12',
            '-vf', 'scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080',
            '-c:v', 'libx264', '-an', '-r', '25', out, '-y'
        ], capture_output=True, timeout=60)
        if os.path.exists(out) and os.path.getsize(out) > 1000:
            trimmed.append(out)

    if not trimmed:
        print("No valid trimmed clips")
        return None

    # Concatenate clips
    concat_file = os.path.join(tmp, 'concat.txt')
    concat_out = os.path.join(tmp, 'concat.mp4')
    with open(concat_file, 'w') as f:
        for t in trimmed:
            f.write(f"file '{t}'\n")

    subprocess.run([
        'ffmpeg', '-f', 'concat', '-safe', '0',
        '-i', concat_file, '-c', 'copy', concat_out, '-y'
    ], capture_output=True, timeout=60)

    # Build final video with DR SHEMA watermark
    title = data.get('title', 'DR SHEMA')[:50]
    title = re.sub(r"[^a-zA-Z0-9 ]", ' ', title).strip()
    output = os.path.join(tmp, 'final.mp4')

    has_logo = os.path.exists(LOGO_PATH)
    channel = data.get('channel', 'news')

    bar_colors = {
        'news': '0xFF0000',
        'heroes': '0xFFD700',
        'africa': '0x00AA00',
        'motivation': '0xFF6600',
        'advice': '0x0066FF',
        'sports': '0xFF0000'
    }
    bar_color = bar_colors.get(channel, '0xFF0000')

    cmd = ['ffmpeg', '-i', concat_out]
    if has_logo:
        cmd += ['-i', LOGO_PATH]
    if has_audio:
        cmd += ['-i', audio_mp3]

    if has_logo:
        fc = (
            f"[0:v]scale=1920:1080,setsar=1[vb];"
            f"[1:v]scale=120:120[lg];"
            f"[vb][lg]overlay=W-130:10[vl];"
            f"[vl]drawtext=text='DR SHEMA':fontsize=22:fontcolor=gold:bordercolor=black:borderw=2:x=W-125:y=135[vt];"
            f"[vt]drawrect=x=0:y=H-55:w=W:h=55:color={bar_color}@0.9[vbar];"
            f"[vbar]drawtext=text='{title}':fontsize=26:fontcolor=white:bordercolor=black:borderw=2:x=(W-text_w)/2:y=H-42[vf]"
        )
    else:
        fc = (
            f"[0:v]scale=1920:1080,setsar=1[vb];"
            f"[vb]drawtext=text='DR SHEMA':fontsize=28:fontcolor=gold:bordercolor=black:borderw=2:x=20:y=20[vt];"
            f"[vt]drawrect=x=0:y=H-55:w=W:h=55:color={bar_color}@0.9[vbar];"
            f"[vbar]drawtext=text='{title}':fontsize=26:fontcolor=white:bordercolor=black:borderw=2:x=(W-text_w)/2:y=H-42[vf]"
        )

    cmd += ['-filter_complex', fc, '-map', '[vf]']

    if has_audio:
        audio_idx = 2 if has_logo else 1
        cmd += ['-map', f'{audio_idx}:a']

    cmd += [
        '-c:v', 'libx264',
        '-c:a', 'aac' if has_audio else 'copy',
        '-shortest',
        '-r', '25',
        '-preset', 'fast',
        output, '-y'
    ]

    print("Building final video...")
    result = subprocess.run(cmd, capture_output=True, timeout=300)

    if os.path.exists(output) and os.path.getsize(output) > 10000:
        size_mb = os.path.getsize(output) / (1024 * 1024)
        print(f"Video built successfully: {size_mb:.1f}MB")
        with open(output, 'rb') as f:
            return base64.b64encode(f.read()).decode()
    else:
        print(f"FFmpeg error: {result.stderr[-300:].decode()}")
        return None


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'DR SHEMA Video Service is running', 'ready': True})


@app.route('/build', methods=['POST'])
def build():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        print(f"Building video: {data.get('title', 'unknown')}")
        video_b64 = build_video(data)

        if video_b64:
            return jsonify({'success': True, 'video': video_b64})
        else:
            return jsonify({'success': False, 'error': 'Video build failed'}), 500

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8765))
    app.run(host='0.0.0.0', port=port)

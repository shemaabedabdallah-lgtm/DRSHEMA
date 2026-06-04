import os
import requests
import subprocess
import base64
import tempfile
import shutil
import asyncio
from flask import Flask, request, jsonify

app = Flask(__name__)
WATERMARK_TEXT = "DR SHEMA"

def generate_voice(script, audio_path):
    """Try edge-tts first, then espeak"""
    
    # Method 1: edge-tts (Microsoft, natural voice)
    try:
        import edge_tts
        mp3_path = audio_path.replace('.wav', '.mp3')
        
        async def do_tts():
            communicate = edge_tts.Communicate(script[:8000], "en-US-GuyNeural")
            await communicate.save(mp3_path)
        
        asyncio.run(do_tts())
        
        if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 1000:
            subprocess.run(["ffmpeg", "-y", "-i", mp3_path, audio_path],
                         check=True, capture_output=True, timeout=30)
            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
                print(f"edge-tts SUCCESS: {os.path.getsize(audio_path)} bytes")
                return True
    except Exception as e:
        print(f"edge-tts failed: {e}")

    # Method 2: espeak (system installed via Docker)
    try:
        subprocess.run(
            ["espeak", "-v", "en+m3", "-s", "145", "-p", "35", "-w", audio_path, script[:8000]],
            check=True, capture_output=True, timeout=120
        )
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
            print(f"espeak SUCCESS: {os.path.getsize(audio_path)} bytes")
            return True
    except Exception as e:
        print(f"espeak failed: {e}")

    # Method 3: espeak-ng
    try:
        subprocess.run(
            ["espeak-ng", "-v", "en-us+m3", "-s", "145", "-p", "35", "-w", audio_path, script[:8000]],
            check=True, capture_output=True, timeout=120
        )
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
            print(f"espeak-ng SUCCESS: {os.path.getsize(audio_path)} bytes")
            return True
    except Exception as e:
        print(f"espeak-ng failed: {e}")

    print("All TTS failed")
    return False

@app.route("/health", methods=["GET"])
def health():
    tts = []
    try:
        import edge_tts
        tts.append("edge-tts")
    except:
        pass
    for cmd in ["espeak", "espeak-ng", "flite"]:
        try:
            subprocess.run([cmd, "--version"], capture_output=True, timeout=5)
            tts.append(cmd)
        except:
            pass
    return jsonify({"status": "ok", "service": "DR SHEMA Docker", "tts": tts})

@app.route("/build", methods=["POST"])
def build_video():
    data = request.json or {}
    title = data.get("title", "DR SHEMA News")
    script = data.get("script", "Welcome to DR SHEMA.")
    clip_urls = [data.get("clip1_url"), data.get("clip2_url"), data.get("clip3_url")]
    clip_urls = [u for u in clip_urls if u]

    work_dir = tempfile.mkdtemp()
    try:
        # Generate voice
        audio_path = os.path.join(work_dir, "voice.wav")
        has_audio = generate_voice(script, audio_path)

        # Download clips
        clip_paths = []
        for i, url in enumerate(clip_urls[:3]):
            try:
                clip_path = os.path.join(work_dir, f"clip{i}.mp4")
                r = requests.get(url, timeout=60, stream=True)
                with open(clip_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=524288):
                        f.write(chunk)
                if os.path.exists(clip_path) and os.path.getsize(clip_path) > 1000:
                    clip_paths.append(clip_path)
            except Exception as e:
                print(f"Clip {i} error: {e}")

        if not clip_paths:
            return jsonify({"success": False, "error": "No clips"}), 400

        # Concatenate clips
        if len(clip_paths) > 1:
            concat_list = os.path.join(work_dir, "concat.txt")
            with open(concat_list, "w") as f:
                for p in clip_paths:
                    f.write(f"file '{p}'\n")
            concat_path = os.path.join(work_dir, "concat.mp4")
            subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                          "-i", concat_list, "-c", "copy", concat_path],
                         check=True, capture_output=True, timeout=120)
            main_clip = concat_path
        else:
            main_clip = clip_paths[0]

        # Build video - VERY compressed to fit n8n memory
        output_path = os.path.join(work_dir, "output.mp4")
        safe_title = title.replace("'", "").replace(":", "-").replace('"', '')[:50]
        filters = (
            f"scale=640:360,"
            f"drawtext=text='{WATERMARK_TEXT}':fontsize=24:fontcolor=white@0.8"
            f":x=10:y=10:shadowcolor=black:shadowx=2:shadowy=2,"
            f"drawtext=text='{safe_title}':fontsize=18:fontcolor=yellow"
            f":x=(w-text_w)/2:y=h-40:box=1:boxcolor=black@0.5:boxborderw=5"
        )

        if has_audio:
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1", "-i", main_clip,
                "-i", audio_path,
                "-vf", filters,
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "38",
                "-vb", "150k",
                "-c:a", "aac", "-b:a", "64k",
                "-shortest", "-t", "480",
                output_path
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-i", main_clip,
                "-vf", filters,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "38",
                "-vb", "150k", "-an", "-t", "300",
                output_path
            ]

        subprocess.run(cmd, check=True, capture_output=True, timeout=600)

        size = os.path.getsize(output_path)
        print(f"Output size: {size} bytes")

        with open(output_path, "rb") as f:
            video_b64 = base64.b64encode(f.read()).decode()

        return jsonify({"success": True, "video": video_b64, "title": title, "has_audio": has_audio})

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"success": False, "error": str(e)[:300]}), 500
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=False)

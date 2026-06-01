import os
import requests
import subprocess
import base64
import tempfile
import shutil
from flask import Flask, request, jsonify

app = Flask(__name__)

WATERMARK_TEXT = "DR SHEMA"

def generate_voice(script, audio_path):
    for cmd, args in [
        ("espeak", ["espeak", "-w", audio_path, "-s", "145", "-p", "40"]),
        ("espeak-ng", ["espeak-ng", "-w", audio_path, "-s", "145"]),
        ("flite", ["flite", "-t", script[:500], "-o", audio_path]),
    ]:
        try:
            if cmd == "flite":
                subprocess.run(args, check=True, capture_output=True, timeout=60)
            else:
                p = subprocess.Popen(args, stdin=subprocess.PIPE, capture_output=True)
                p.communicate(input=script[:800].encode(), timeout=60)
            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                return True
        except:
            continue
    return False

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "DR SHEMA Video Builder", "ram": "2GB"})

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

        # Download clips (up to 3)
        clip_paths = []
        for i, url in enumerate(clip_urls[:3]):
            try:
                clip_path = os.path.join(work_dir, f"clip{i}.mp4")
                r = requests.get(url, timeout=30, stream=True)
                with open(clip_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=524288):
                        f.write(chunk)
                clip_paths.append(clip_path)
            except:
                continue

        if not clip_paths:
            return jsonify({"success": False, "error": "No clips downloaded"}), 400

        # Concatenate clips if multiple
        if len(clip_paths) > 1:
            concat_list = os.path.join(work_dir, "concat.txt")
            with open(concat_list, "w") as f:
                for p in clip_paths:
                    f.write(f"file '{p}'\n")
            concat_path = os.path.join(work_dir, "concat.mp4")
            subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_list, "-c", "copy", concat_path
            ], check=True, capture_output=True, timeout=60)
            main_clip = concat_path
        else:
            main_clip = clip_paths[0]

        # Build final video
        output_path = os.path.join(work_dir, "output.mp4")
        safe_title = title.replace("'", "").replace(":", "-")[:50]
        filters = (
            f"scale=1280:720,"
            f"drawtext=text='{WATERMARK_TEXT}':fontsize=36:fontcolor=white@0.8"
            f":x=20:y=20:shadowcolor=black:shadowx=2:shadowy=2,"
            f"drawtext=text='{safe_title}':fontsize=28:fontcolor=yellow"
            f":x=(w-text_w)/2:y=h-70:box=1:boxcolor=black@0.5:boxborderw=8"
        )

        if has_audio:
            cmd = [
                "ffmpeg", "-y",
                "-i", main_clip, "-i", audio_path,
                "-vf", filters,
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "fast", "-crf", "28",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest", "-t", "300",  # up to 5 minutes
                output_path
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", main_clip,
                "-vf", filters,
                "-c:v", "libx264", "-preset", "fast", "-crf", "28",
                "-an", "-t", "300",
                output_path
            ]

        subprocess.run(cmd, check=True, capture_output=True, timeout=360)

        with open(output_path, "rb") as f:
            video_b64 = base64.b64encode(f.read()).decode()

        return jsonify({"success": True, "video": video_b64, "title": title})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)[:200]}), 500
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=False)

import os
import requests
import subprocess
import base64
import tempfile
import shutil
from flask import Flask, request, jsonify

app = Flask(__name__)

WATERMARK_TEXT = "DR SHEMA"

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "DR SHEMA Video Builder"})

@app.route("/build", methods=["POST"])
def build_video():
    data = request.json or {}
    title = data.get("title", "DR SHEMA News")
    script = data.get("script", "Welcome to DR SHEMA.")
    clip_urls = [data.get("clip1_url"), data.get("clip2_url"), data.get("clip3_url")]
    clip_urls = [u for u in clip_urls if u]

    work_dir = tempfile.mkdtemp()
    try:
        # Voice with flite
        audio_path = os.path.join(work_dir, "voice.wav")
        subprocess.run(
            ["flite", "-t", script[:300], "-o", audio_path],
            check=True, capture_output=True, timeout=30
        )

        # Download ONE clip
        clip_path = os.path.join(work_dir, "clip.mp4")
        if not clip_urls:
            return jsonify({"success": False, "error": "No clip URL"}), 400
        r = requests.get(clip_urls[0], timeout=30, stream=True)
        with open(clip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=524288):
                f.write(chunk)

        # FFmpeg - very compressed output for small file size
        output_path = os.path.join(work_dir, "output.mp4")
        safe_title = title.replace("'", "").replace(":", "-")[:40]
        filters = (
            f"scale=640:360,"
            f"drawtext=text='{WATERMARK_TEXT}':fontsize=20:fontcolor=white@0.7:x=10:y=10:shadowcolor=black:shadowx=1:shadowy=1,"
            f"drawtext=text='{safe_title}':fontsize=16:fontcolor=yellow:x=(w-text_w)/2:y=h-40:box=1:boxcolor=black@0.5:boxborderw=4"
        )
        subprocess.run([
            "ffmpeg", "-y",
            "-i", clip_path, "-i", audio_path,
            "-vf", filters,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35",
            "-vb", "300k",
            "-c:a", "aac", "-b:a", "48k",
            "-shortest", "-t", "45",
            output_path
        ], check=True, capture_output=True, timeout=120)

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

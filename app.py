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
    title     = data.get("title", "DR SHEMA News")
    script    = data.get("script", "Welcome to DR SHEMA.")
    clip_urls = [data.get("clip1_url"), data.get("clip2_url"), data.get("clip3_url")]
    clip_urls = [u for u in clip_urls if u]

    work_dir = tempfile.mkdtemp()

    try:
        # 1. Voice with flite
        audio_path = os.path.join(work_dir, "voice.wav")
        short_script = script[:300]
        try:
            subprocess.run(
                ["flite", "-t", short_script, "-o", audio_path],
                check=True, capture_output=True, timeout=30
            )
        except Exception as e:
            return jsonify({"success": False, "error": f"Voice failed: {str(e)[:100]}"}), 500

        # 2. Download ONE clip only
        clip_path = os.path.join(work_dir, "clip.mp4")
        if not clip_urls:
            return jsonify({"success": False, "error": "No clip URL provided"}), 400
        try:
            r = requests.get(clip_urls[0], timeout=30, stream=True)
            with open(clip_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=524288):
                    f.write(chunk)
        except Exception as e:
            return jsonify({"success": False, "error": f"Clip download failed: {str(e)[:100]}"}), 500

        # 3. FFmpeg watermark + title + audio
        output_path = os.path.join(work_dir, "output.mp4")
        safe_title = title.replace("'", "").replace(":", "-")[:50]
        filters = (
            f"drawtext=text='{WATERMARK_TEXT}':fontsize=32:fontcolor=white@0.7"
            f":x=20:y=20:shadowcolor=black:shadowx=2:shadowy=2,"
            f"drawtext=text='{safe_title}':fontsize=24:fontcolor=yellow"
            f":x=(w-text_w)/2:y=h-60:box=1:boxcolor=black@0.5:boxborderw=6"
        )
        try:
            subprocess.run([
                "ffmpeg", "-y",
                "-i", clip_path,
                "-i", audio_path,
                "-vf", filters,
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                "-c:a", "aac", "-b:a", "64k",
                "-shortest", "-t", "60",
                output_path
            ], check=True, capture_output=True, timeout=120)
        except Exception as e:
            return jsonify({"success": False, "error": f"FFmpeg failed: {str(e)[:100]}"}), 500

        # 4. Return base64 video
        with open(output_path, "rb") as f:
            video_b64 = base64.b64encode(f.read()).decode()

        return jsonify({"success": True, "video": video_b64, "title": title})

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=False)

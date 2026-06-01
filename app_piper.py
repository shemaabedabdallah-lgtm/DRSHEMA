import os
import requests
import subprocess
import base64
import tempfile
import shutil
from flask import Flask, request, jsonify

app = Flask(__name__)

WATERMARK_TEXT = "DR SHEMA"
PIPER_MODEL_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
PIPER_CONFIG_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"
PIPER_DIR = "/tmp/piper"
PIPER_MODEL = "/tmp/piper/voice.onnx"
PIPER_CONFIG = "/tmp/piper/voice.onnx.json"
PIPER_BIN = "/tmp/piper/piper"
PIPER_READY = False

def setup_piper():
    global PIPER_READY
    if PIPER_READY:
        return True
    try:
        os.makedirs(PIPER_DIR, exist_ok=True)

        # Download piper binary
        if not os.path.exists(PIPER_BIN):
            piper_tar = "/tmp/piper.tar.gz"
            subprocess.run([
                "wget", "-q", "-O", piper_tar,
                "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz"
            ], check=True, timeout=120)
            subprocess.run(["tar", "-xzf", piper_tar, "-C", "/tmp/"], check=True)
            subprocess.run(["chmod", "+x", PIPER_BIN], check=True)

        # Download voice model
        if not os.path.exists(PIPER_MODEL):
            subprocess.run(["wget", "-q", "-O", PIPER_MODEL, PIPER_MODEL_URL], check=True, timeout=120)
            subprocess.run(["wget", "-q", "-O", PIPER_CONFIG, PIPER_CONFIG_URL], check=True, timeout=60)

        PIPER_READY = True
        return True
    except Exception as e:
        print(f"Piper setup failed: {e}")
        return False

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "DR SHEMA Video Builder", "tts": "piper"})

@app.route("/build", methods=["POST"])
def build_video():
    data = request.json or {}
    title     = data.get("title", "DR SHEMA News")
    script    = data.get("script", "Welcome to DR SHEMA.")
    audio_url = data.get("audio_url", "")
    clip_urls = [data.get("clip1_url"), data.get("clip2_url"), data.get("clip3_url")]
    clip_urls = [u for u in clip_urls if u]

    work_dir = tempfile.mkdtemp()

    try:
        audio_path = os.path.join(work_dir, "voice.wav")

        # Use provided audio URL if available (HeyGen voice)
        if audio_url:
            try:
                r = requests.get(audio_url, timeout=30, stream=True)
                with open(audio_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=524288):
                        f.write(chunk)
            except:
                audio_url = ""  # Fall back to Piper

        # Use Piper TTS if no audio URL
        if not audio_url or not os.path.exists(audio_path):
            piper_ok = setup_piper()
            if piper_ok:
                try:
                    short_script = script[:400]
                    result = subprocess.run(
                        [PIPER_BIN, "--model", PIPER_MODEL, "--output_file", audio_path],
                        input=short_script.encode(),
                        check=True, capture_output=True, timeout=60
                    )
                except Exception as e:
                    # Fall back to flite
                    subprocess.run(
                        ["flite", "-t", script[:300], "-o", audio_path],
                        check=True, capture_output=True, timeout=30
                    )
            else:
                # Fall back to flite
                subprocess.run(
                    ["flite", "-t", script[:300], "-o", audio_path],
                    check=True, capture_output=True, timeout=30
                )

        # Download ONE clip
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

        # FFmpeg: watermark + title + audio
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

        with open(output_path, "rb") as f:
            video_b64 = base64.b64encode(f.read()).decode()

        return jsonify({"success": True, "video": video_b64, "title": title})

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=False)

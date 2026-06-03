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
    """Generate voice using gTTS (Google Text to Speech) - no system packages needed"""
    try:
        from gtts import gTTS
        import math
        
        # gTTS has a limit per request, split into chunks
        max_chars = 5000
        chunks = [script[i:i+max_chars] for i in range(0, min(len(script), 15000), max_chars)]
        
        chunk_files = []
        work_dir = os.path.dirname(audio_path)
        
        for i, chunk in enumerate(chunks):
            chunk_mp3 = os.path.join(work_dir, f"chunk_{i}.mp3")
            tts = gTTS(text=chunk, lang='en', slow=False)
            tts.save(chunk_mp3)
            chunk_files.append(chunk_mp3)
        
        if len(chunk_files) == 1:
            # Convert single mp3 to wav
            subprocess.run([
                "ffmpeg", "-y", "-i", chunk_files[0], audio_path
            ], check=True, capture_output=True, timeout=30)
        else:
            # Concatenate all chunks
            concat_list = os.path.join(work_dir, "audio_concat.txt")
            with open(concat_list, "w") as f:
                for cf in chunk_files:
                    f.write(f"file '{cf}'\n")
            combined_mp3 = os.path.join(work_dir, "combined.mp3")
            subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_list, "-c", "copy", combined_mp3
            ], check=True, capture_output=True, timeout=60)
            subprocess.run([
                "ffmpeg", "-y", "-i", combined_mp3, audio_path
            ], check=True, capture_output=True, timeout=30)
        
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
            return True
    except Exception as e:
        print(f"gTTS failed: {e}")
    
    # Fallback to espeak
    for args in [
        ["espeak", "-v", "en+m3", "-s", "145", "-p", "35", "-w", audio_path, script[:1500]],
        ["espeak-ng", "-v", "en-us+m3", "-s", "145", "-p", "35", "-w", audio_path, script[:1500]],
        ["flite", "-t", script[:800], "-o", audio_path],
    ]:
        try:
            subprocess.run(args, check=True, capture_output=True, timeout=90)
            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                return True
        except:
            continue
    return False

@app.route("/health", methods=["GET"])
def health():
    try:
        from gtts import gTTS
        tts_engine = "gTTS"
    except:
        tts_engine = "espeak/flite"
    return jsonify({"status": "ok", "service": "DR SHEMA Video Builder", "tts": tts_engine})

@app.route("/build", methods=["POST"])
def build_video():
    data = request.json or {}
    title = data.get("title", "DR SHEMA News")
    script = data.get("script", "Welcome to DR SHEMA.")
    clip_urls = [data.get("clip1_url"), data.get("clip2_url"), data.get("clip3_url")]
    clip_urls = [u for u in clip_urls if u]

    work_dir = tempfile.mkdtemp()
    try:
        audio_path = os.path.join(work_dir, "voice.wav")
        has_audio = generate_voice(script, audio_path)

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
            return jsonify({"success": False, "error": "No clips"}), 400

        if len(clip_paths) > 1:
            concat_list = os.path.join(work_dir, "concat.txt")
            with open(concat_list, "w") as f:
                for p in clip_paths:
                    f.write(f"file '{p}'\n")
            concat_path = os.path.join(work_dir, "concat.mp4")
            subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", concat_path], check=True, capture_output=True, timeout=120)
            main_clip = concat_path
        else:
            main_clip = clip_paths[0]

        output_path = os.path.join(work_dir, "output.mp4")
        safe_title = title.replace("'", "").replace(":", "-")[:50]
        filters = (
            f"scale=640:360,"
            f"drawtext=text='{WATERMARK_TEXT}':fontsize=24:fontcolor=white@0.8:x=10:y=10:shadowcolor=black:shadowx=2:shadowy=2,"
            f"drawtext=text='{safe_title}':fontsize=18:fontcolor=yellow:x=(w-text_w)/2:y=h-40:box=1:boxcolor=black@0.5:boxborderw=5"
        )

        if has_audio:
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1",
                "-i", main_clip,
                "-i", audio_path,
                "-vf", filters,
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "38",
                "-vb", "200k",
                "-c:a", "aac", "-b:a", "64k",
                "-shortest",
                "-t", "600",
                output_path
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", main_clip,
                "-vf", filters,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "38",
                "-vb", "200k", "-an",
                "-t", "600",
                output_path
            ]

        subprocess.run(cmd, check=True, capture_output=True, timeout=600)

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

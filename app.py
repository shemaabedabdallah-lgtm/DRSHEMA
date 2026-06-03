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

async def edge_tts_generate(text, output_path):
    """Use Microsoft Edge TTS - free, no system packages needed"""
    import edge_tts
    communicate = edge_tts.Communicate(text, "en-US-GuyNeural")
    await communicate.save(output_path)

def generate_voice(script, audio_path):
    work_dir = os.path.dirname(audio_path)
    
    # Method 1: edge-tts (Microsoft, free, online, male voice)
    try:
        import edge_tts
        mp3_path = os.path.join(work_dir, "voice.mp3")
        asyncio.run(edge_tts_generate(script[:5000], mp3_path))
        if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 1000:
            # Convert mp3 to wav
            subprocess.run(["ffmpeg", "-y", "-i", mp3_path, audio_path],
                         check=True, capture_output=True, timeout=30)
            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
                print(f"edge-tts SUCCESS: {os.path.getsize(audio_path)} bytes")
                return True
    except Exception as e:
        print(f"edge-tts failed: {e}")

    # Method 2: gTTS (Google, free, online)
    try:
        from gtts import gTTS
        chunks = [script[i:i+3000] for i in range(0, min(len(script), 9000), 3000)]
        mp3_files = []
        for i, chunk in enumerate(chunks):
            mp3 = os.path.join(work_dir, f"g{i}.mp3")
            gTTS(text=chunk, lang='en').save(mp3)
            mp3_files.append(mp3)
        
        if len(mp3_files) == 1:
            subprocess.run(["ffmpeg", "-y", "-i", mp3_files[0], audio_path],
                         check=True, capture_output=True, timeout=30)
        else:
            lst = os.path.join(work_dir, "gl.txt")
            with open(lst, "w") as f:
                for m in mp3_files:
                    f.write(f"file '{m}'\n")
            combined = os.path.join(work_dir, "gc.mp3")
            subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                          "-i", lst, "-c", "copy", combined],
                         check=True, capture_output=True, timeout=60)
            subprocess.run(["ffmpeg", "-y", "-i", combined, audio_path],
                         check=True, capture_output=True, timeout=30)
        
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
            print(f"gTTS SUCCESS: {os.path.getsize(audio_path)} bytes")
            return True
    except Exception as e:
        print(f"gTTS failed: {e}")

    print("All TTS methods failed")
    return False

@app.route("/health", methods=["GET"])
def health():
    available = []
    try:
        import edge_tts
        available.append("edge-tts")
    except:
        pass
    try:
        from gtts import gTTS
        available.append("gtts")
    except:
        pass
    return jsonify({"status": "ok", "tts": available})

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
        print(f"Voice: {has_audio}, size: {os.path.getsize(audio_path) if has_audio else 0}")

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
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35",
                "-vb", "300k",
                "-c:a", "aac", "-b:a", "96k",
                "-shortest", "-t", "600",
                output_path
            ]
        else:
            cmd = [
                "ffmpeg", "-y", "-i", main_clip,
                "-vf", filters,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35",
                "-vb", "300k", "-an", "-t", "300",
                output_path
            ]

        subprocess.run(cmd, check=True, capture_output=True, timeout=600)

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

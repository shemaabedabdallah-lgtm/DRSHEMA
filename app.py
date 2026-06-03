import os
import requests
import subprocess
import base64
import tempfile
import shutil
from flask import Flask, request, jsonify

app = Flask(__name__)
WATERMARK_TEXT = "DR SHEMA"

def generate_voice_gtts(script, audio_path):
    """Try Google TTS online"""
    try:
        from gtts import gTTS
        chunks = []
        chunk_size = 3000
        text = script[:12000]
        for i in range(0, len(text), chunk_size):
            chunks.append(text[i:i+chunk_size])
        
        work_dir = os.path.dirname(audio_path)
        mp3_files = []
        for i, chunk in enumerate(chunks):
            mp3_path = os.path.join(work_dir, f"chunk_{i}.mp3")
            tts = gTTS(text=chunk, lang='en', slow=False)
            tts.save(mp3_path)
            mp3_files.append(mp3_path)
        
        if len(mp3_files) == 1:
            subprocess.run(["ffmpeg", "-y", "-i", mp3_files[0], audio_path],
                         check=True, capture_output=True, timeout=60)
        else:
            concat_list = os.path.join(work_dir, "alist.txt")
            with open(concat_list, "w") as f:
                for mp3 in mp3_files:
                    f.write(f"file '{mp3}'\n")
            combined = os.path.join(work_dir, "combined.mp3")
            subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                          "-i", concat_list, "-c", "copy", combined],
                         check=True, capture_output=True, timeout=60)
            subprocess.run(["ffmpeg", "-y", "-i", combined, audio_path],
                         check=True, capture_output=True, timeout=60)
        
        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
            print(f"gTTS SUCCESS: {os.path.getsize(audio_path)} bytes")
            return True
    except Exception as e:
        print(f"gTTS FAILED: {e}")
    return False

def generate_voice_espeak(script, audio_path):
    """Try espeak/espeak-ng"""
    for cmd in [
        ["espeak", "-v", "en+m3", "-s", "145", "-p", "35", "-w", audio_path, script[:5000]],
        ["espeak-ng", "-v", "en-us+m3", "-s", "145", "-p", "35", "-w", audio_path, script[:5000]],
        ["espeak", "-w", audio_path, script[:3000]],
        ["espeak-ng", "-w", audio_path, script[:3000]],
    ]:
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
                print(f"espeak SUCCESS with: {cmd[0]}")
                return True
        except Exception as e:
            print(f"espeak failed {cmd[0]}: {e}")
            continue
    return False

def generate_voice_flite(script, audio_path):
    """Try flite"""
    for voice in ["rms", "awb", "kal", "kal16", "slt", ""]:
        try:
            if voice:
                cmd = ["flite", "-voice", voice, "-t", script[:5000], "-o", audio_path]
            else:
                cmd = ["flite", "-t", script[:3000], "-o", audio_path]
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
            if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
                print(f"flite SUCCESS voice={voice}")
                return True
        except Exception as e:
            print(f"flite failed voice={voice}: {e}")
            continue
    return False

def generate_voice(script, audio_path):
    """Try all TTS methods in order"""
    print(f"Generating voice for script length: {len(script)}")
    
    # Try gTTS first (best quality)
    if generate_voice_gtts(script, audio_path):
        return True
    
    # Try espeak
    if generate_voice_espeak(script, audio_path):
        return True
    
    # Try flite
    if generate_voice_flite(script, audio_path):
        return True
    
    print("ALL TTS METHODS FAILED")
    return False

@app.route("/health", methods=["GET"])
def health():
    tts_available = []
    for cmd in ["espeak", "espeak-ng", "flite"]:
        try:
            subprocess.run([cmd, "--version"], capture_output=True, timeout=5)
            tts_available.append(cmd)
        except:
            pass
    try:
        from gtts import gTTS
        tts_available.append("gtts")
    except:
        pass
    return jsonify({"status": "ok", "service": "DR SHEMA Video Builder", "tts": tts_available})

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
        print(f"Voice generated: {has_audio}")
        if has_audio:
            print(f"Audio file size: {os.path.getsize(audio_path)}")

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
                    print(f"Clip {i} downloaded: {os.path.getsize(clip_path)} bytes")
            except Exception as e:
                print(f"Clip {i} failed: {e}")

        if not clip_paths:
            return jsonify({"success": False, "error": "No clips downloaded"}), 400

        # Concatenate clips
        if len(clip_paths) > 1:
            concat_list = os.path.join(work_dir, "concat.txt")
            with open(concat_list, "w") as f:
                for p in clip_paths:
                    f.write(f"file '{p}'\n")
            concat_path = os.path.join(work_dir, "concat.mp4")
            subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_list, "-c", "copy", concat_path
            ], check=True, capture_output=True, timeout=120)
            main_clip = concat_path
        else:
            main_clip = clip_paths[0]

        # Build final video
        output_path = os.path.join(work_dir, "output.mp4")
        safe_title = title.replace("'", "").replace(":", "-").replace('"', '')[:50]
        filters = (
            f"scale=640:360,"
            f"drawtext=text='{WATERMARK_TEXT}':fontsize=24:fontcolor=white@0.8"
            f":x=10:y=10:shadowcolor=black:shadowx=2:shadowy=2,"
            f"drawtext=text='{safe_title}':fontsize=18:fontcolor=yellow"
            f":x=(w-text_w)/2:y=h-40:box=1:boxcolor=black@0.5:boxborderw=5"
        )

        if has_audio and os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
            print("Building video WITH audio...")
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1",
                "-i", main_clip,
                "-i", audio_path,
                "-vf", filters,
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35",
                "-vb", "300k",
                "-c:a", "aac", "-b:a", "96k",
                "-shortest",
                "-t", "600",
                output_path
            ]
        else:
            print("Building video WITHOUT audio (no TTS available)...")
            cmd = [
                "ffmpeg", "-y",
                "-i", main_clip,
                "-vf", filters,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35",
                "-vb", "300k", "-an",
                "-t", "300",
                output_path
            ]

        result = subprocess.run(cmd, capture_output=True, timeout=600)
        if result.returncode != 0:
            print(f"FFmpeg error: {result.stderr[-500:].decode()}")
            return jsonify({"success": False, "error": "FFmpeg failed"}), 500

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
            return jsonify({"success": False, "error": "Output file too small"}), 500

        print(f"Output video size: {os.path.getsize(output_path)} bytes")

        with open(output_path, "rb") as f:
            video_b64 = base64.b64encode(f.read()).decode()

        return jsonify({
            "success": True,
            "video": video_b64,
            "title": title,
            "has_audio": has_audio
        })

    except Exception as e:
        print(f"Build error: {e}")
        return jsonify({"success": False, "error": str(e)[:300]}), 500
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=False)

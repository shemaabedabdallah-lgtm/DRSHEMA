from flask import Flask, request, jsonify
import subprocess, tempfile, os, requests, asyncio, traceback, base64, textwrap
from PIL import Image, ImageDraw, ImageFont
import io

app = Flask(__name__)
VOICE = "en-US-ChristopherNeural"

CHANNEL_COLORS = {
    'news':       {'bg': '#0A0A2E', 'accent': '#FF4136', 'text': '#FFFFFF'},
    'motivation': {'bg': '#1A0A00', 'accent': '#FF8C00', 'text': '#FFFFFF'},
    'advice':     {'bg': '#0A1A0A', 'accent': '#00C851', 'text': '#FFFFFF'},
    'heroes':     {'bg': '#1A0A1A', 'accent': '#9B59B6', 'text': '#FFFFFF'},
    'africa':     {'bg': '#1A0F00', 'accent': '#F39C12', 'text': '#FFFFFF'},
    'sports':     {'bg': '#0A0A0A', 'accent': '#00B4D8', 'text': '#FFFFFF'},
    'analysis':   {'bg': '#001A0A', 'accent': '#2ECC71', 'text': '#FFFFFF'},
}

def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def fetch_wikipedia_image(topic):
    """Fetch the main image for a topic from Wikipedia"""
    try:
        # Search Wikipedia for the topic
        search_url = "https://en.wikipedia.org/w/api.php"
        params = {
            'action': 'query', 'list': 'search',
            'srsearch': topic, 'srlimit': 1, 'format': 'json'
        }
        r = requests.get(search_url, params=params, timeout=8)
        results = r.json().get('query', {}).get('search', [])
        if not results:
            return None
        page_title = results[0]['title']
        # Get the page image
        img_params = {
            'action': 'query', 'titles': page_title,
            'prop': 'pageimages', 'pithumbsize': 500,
            'format': 'json'
        }
        r2 = requests.get(search_url, params=img_params, timeout=8)
        pages = r2.json().get('query', {}).get('pages', {})
        for page in pages.values():
            thumb = page.get('thumbnail', {})
            if thumb.get('source'):
                return thumb['source']
    except Exception as e:
        print(f"[WIKI] {e}")
    return None

def generate_thumbnail(title, hook, channel, topic_image_url=None, wikipedia_topic=None):
    """Generate a professional 1280x720 thumbnail"""
    W, H = 1280, 720
    colors = CHANNEL_COLORS.get(channel, CHANNEL_COLORS['news'])
    bg_color = hex_to_rgb(colors['bg'])
    accent_color = hex_to_rgb(colors['accent'])

    img = Image.new('RGB', (W, H), bg_color)
    draw = ImageDraw.Draw(img)

    # Try to fetch topic image from Wikipedia if not provided
    topic_img = None
    img_url = topic_image_url
    if not img_url and wikipedia_topic:
        img_url = fetch_wikipedia_image(wikipedia_topic)

    if img_url:
        try:
            r = requests.get(img_url, timeout=10)
            topic_img = Image.open(io.BytesIO(r.content)).convert('RGB')
            # Place image on right side
            iw, ih = topic_img.size
            ratio = H / ih
            nw = int(iw * ratio)
            topic_img = topic_img.resize((nw, H))
            # Paste on right
            paste_x = W - min(nw, W // 2 + 100)
            img.paste(topic_img, (paste_x, 0))
            # Add dark gradient overlay on left for text readability
            for x in range(W):
                alpha = max(0, min(255, int(255 * (1 - (x - paste_x) / (W - paste_x + 1)) * 1.5)))
                if x < paste_x + 200:
                    for y in range(H):
                        try:
                            px = img.getpixel((x, y))
                            blended = tuple(int(bg_color[i] * (alpha/255) + px[i] * (1 - alpha/255)) for i in range(3))
                            img.putpixel((x, y), blended)
                        except:
                            pass
        except Exception as e:
            print(f"[THUMB IMG] {e}")

    # Accent bar on left
    draw.rectangle([(0, 0), (12, H)], fill=accent_color)

    # Channel label top
    try:
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
        font_hook = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
        font_brand = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
    except:
        font_small = ImageFont.load_default()
        font_title = font_small
        font_hook = font_small
        font_brand = font_small

    # Channel badge
    channel_label = channel.upper().replace('news', 'BREAKING NEWS').replace('motivation', 'DAILY MOTIVATION').replace('advice', 'ADVICE').replace('heroes', 'WORLD HEROES').replace('africa', 'AFRICA RISING').replace('sports', 'SPORTS').replace('analysis', 'MATCH ANALYSIS')
    badge_w = 280
    draw.rectangle([(30, 30), (30 + badge_w, 70)], fill=accent_color)
    draw.text((40, 38), channel_label[:20], font=font_small, fill=(255, 255, 255))

    # Main title - wrap at 22 chars per line
    max_chars = 22
    words = title.split()
    lines = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 <= max_chars:
            current += (" " if current else "") + word
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    lines = lines[:3]

    y_title = 100
    for line in lines:
        # Shadow
        draw.text((34, y_title + 4), line.upper(), font=font_title, fill=(0, 0, 0))
        draw.text((30, y_title), line.upper(), font=font_title, fill=(255, 255, 255))
        y_title += 75

    # Hook text
    if hook:
        hook_short = hook[:80] + ("..." if len(hook) > 80 else "")
        hook_lines = textwrap.wrap(hook_short, width=35)[:2]
        y_hook = y_title + 20
        for hl in hook_lines:
            draw.text((32, y_hook + 3), hl, font=font_hook, fill=(0, 0, 0))
            draw.text((30, y_hook), hl, font=font_hook, fill=accent_color)
            y_hook += 44

    # Bottom brand bar
    draw.rectangle([(0, H - 60), (W, H)], fill=accent_color)
    draw.text((30, H - 45), "DOCTOR SHEMA  |  @drshemaaa", font=font_brand, fill=(255, 255, 255))

    # Return as base64
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=85)
    return base64.b64encode(buf.getvalue()).decode()

async def edge_tts(text, path):
    import edge_tts
    await edge_tts.Communicate(text, VOICE).save(path)

def build_srt(script, audio_path, srt_path):
    try:
        r = subprocess.run(['ffprobe','-v','error','-show_entries','format=duration',
            '-of','default=noprint_wrappers=1:nokey=1',audio_path],capture_output=True,text=True)
        dur = float(r.stdout.strip() or '60')
        words = script.split()
        tpw = dur / max(len(words),1)
        def fmt(t):
            h,m,s,ms=int(t//3600),int((t%3600)//60),int(t%60),int((t%1)*1000)
            return f"{h:02}:{m:02}:{s:02},{ms:03}"
        with open(srt_path,'w',encoding='utf-8') as f:
            for i in range(0,len(words),3):
                c=words[i:i+3]; st=i*tpw; en=(i+len(c))*tpw
                f.write(f"{i//3+1}\n{fmt(st)} --> {fmt(en)}\n{' '.join(c).upper()}\n\n")
        return True
    except: return False

def gen_audio(script, tmpdir):
    ap=os.path.join(tmpdir,'speech.mp3'); sp=os.path.join(tmpdir,'captions.srt')
    try:
        asyncio.run(edge_tts(script,ap))
        if os.path.exists(ap) and os.path.getsize(ap)>1000:
            build_srt(script,ap,sp); return ap,sp
    except: pass
    try:
        from gtts import gTTS
        gTTS(text=script,lang='en',slow=False).save(ap)
        if os.path.exists(ap) and os.path.getsize(ap)>1000:
            build_srt(script,ap,sp); return ap,sp
    except: pass
    return None,None

def dl(url,path):
    r=requests.get(url,stream=True,timeout=60)
    with open(path,'wb') as f:
        for c in r.iter_content(8192): f.write(c)

def loop_clip(src,dur,out,idx):
    try:
        r=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration',
            '-of','default=noprint_wrappers=1:nokey=1',src],capture_output=True,text=True)
        cd=float(r.stdout.strip() or '5')
        if cd>=dur:
            subprocess.run(['ffmpeg','-y','-i',src,'-t',str(dur),
                '-vf','scale=320:180,setsar=1','-r','20','-an',
                '-c:v','libx264','-preset','ultrafast','-b:v','100k',out],capture_output=True)
        else:
            lst=out+'_l.txt'
            with open(lst,'w') as f:
                for _ in range(int(dur/cd)+2): f.write(f"file '{src}'\n")
            lp=out+'_lp.mp4'
            subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i',lst,'-t',str(dur),
                '-vf','scale=320:180,setsar=1','-r','20','-an',
                '-c:v','libx264','-preset','ultrafast','-b:v','100k',lp],capture_output=True)
            if os.path.exists(lp): os.rename(lp,out)
            try: os.remove(lst)
            except: pass
        return os.path.exists(out) and os.path.getsize(out)>0
    except Exception as e:
        print(f"[CLIP] {e}"); return False

@app.route('/build',methods=['POST'])
def build_video():
    try:
        data=request.get_json()
        script=data.get('script',''); title=data.get('title','video')
        c1=data.get('clip1_url',''); c2=data.get('clip2_url',''); c3=data.get('clip3_url','')
        channel=data.get('channel','news')
        hook=data.get('hook','')
        wikipedia_topic=data.get('wikipedia_topic','')
        print(f"[BUILD] {title[:50]}")

        # Generate thumbnail (non-blocking, runs fast)
        thumb_b64 = None
        try:
            thumb_b64 = generate_thumbnail(title, hook, channel, wikipedia_topic=wikipedia_topic)
            print(f"[THUMB] Generated OK")
        except Exception as te:
            print(f"[THUMB] Failed: {te}")

        with tempfile.TemporaryDirectory() as tmp:
            ap,sp=gen_audio(script,tmp)
            if not ap: return jsonify({'success':False,'error':'TTS failed'}),500
            has_srt=sp and os.path.exists(sp) and os.path.getsize(sp)>10
            r=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration',
                '-of','default=noprint_wrappers=1:nokey=1',ap],capture_output=True,text=True)
            dur=min(float(r.stdout.strip() or '45'),240)
            urls=[u for u in [c1,c2,c3] if u]
            cdur=dur/max(len(urls),1); procs=[]
            for i,u in enumerate(urls):
                raw=os.path.join(tmp,f'r{i}.mp4'); out=os.path.join(tmp,f'p{i}.mp4')
                try:
                    dl(u,raw)
                    if loop_clip(raw,cdur,out,i): procs.append(out)
                except Exception as e: print(f"[CLIP {i}] {e}")
            if not procs: return jsonify({'success':False,'error':'No clips'}),500
            lst=os.path.join(tmp,'l.txt')
            with open(lst,'w') as f:
                for p in procs: f.write(f"file '{p}'\n")
            cat=os.path.join(tmp,'cat.mp4')
            subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i',lst,'-c','copy',cat],capture_output=True)
            fin=os.path.join(tmp,'final.mp4')
            if has_srt:
                se=sp.replace('\\','/').replace(':','\\:')
                vf=(f"scale=320:180,subtitles='{se}':force_style='"
                    f"FontName=Arial,FontSize=14,Bold=1,PrimaryColour=&H00FFFFFF,"
                    f"OutlineColour=&H00000000,Outline=2,Alignment=2,MarginV=10'")
                r2=subprocess.run(['ffmpeg','-y','-i',cat,'-i',ap,
                    '-map','0:v:0','-map','1:a:0','-vf',vf,
                    '-c:v','libx264','-preset','ultrafast','-b:v','120k',
                    '-c:a','aac','-b:a','48k','-shortest',fin],capture_output=True,timeout=300)
                if r2.returncode!=0:
                    subprocess.run(['ffmpeg','-y','-i',cat,'-i',ap,
                        '-map','0:v:0','-map','1:a:0','-vf','scale=320:180',
                        '-c:v','libx264','-preset','ultrafast','-b:v','100k',
                        '-c:a','aac','-b:a','48k','-shortest',fin],capture_output=True)
            else:
                subprocess.run(['ffmpeg','-y','-i',cat,'-i',ap,
                    '-map','0:v:0','-map','1:a:0','-vf','scale=320:180',
                    '-c:v','libx264','-preset','ultrafast','-b:v','100k',
                    '-c:a','aac','-b:a','48k','-shortest',fin],capture_output=True)
            if not os.path.exists(fin) or os.path.getsize(fin)==0:
                return jsonify({'success':False,'error':'Final failed'}),500
            sz=os.path.getsize(fin)
            print(f"[BUILD] {sz/1024/1024:.1f}MB")
            with open(fin,'rb') as f: vb64=base64.b64encode(f.read()).decode()
            return jsonify({'success':True,'has_audio':True,'has_captions':has_srt,
                'has_thumbnail': thumb_b64 is not None,
                'thumbnail': thumb_b64,
                'file_size':sz,'duration':round(dur,1),
                'title':title,'video':vb64})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success':False,'error':str(e)}),500

@app.route('/health',methods=['GET'])
def health():
    return jsonify({'status':'ok','voice':VOICE,'quality':'320x180','thumbnail':'enabled'})

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))

from flask import Flask, request, jsonify
import subprocess, tempfile, os, requests, asyncio, traceback, base64, textwrap
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import io, math

app = Flask(__name__)
VOICE = "en-US-ChristopherNeural"

CHANNEL_COLORS = {
    'news':       {'bg': '#0A0A2E', 'accent': '#FF4136', 'text': '#FFFFFF'},
    'motivation': {'bg': '#1A0A00', 'accent': '#FFD700', 'text': '#FFFFFF'},
    'advice':     {'bg': '#0A1A0A', 'accent': '#00C851', 'text': '#FFFFFF'},
    'heroes':     {'bg': '#1A0A1A', 'accent': '#FFD700', 'text': '#FFFFFF'},
    'africa':     {'bg': '#1A0F00', 'accent': '#F39C12', 'text': '#FFFFFF'},
    'sports':     {'bg': '#0A0A0A', 'accent': '#00B4D8', 'text': '#FFFFFF'},
    'analysis':   {'bg': '#001A0A', 'accent': '#2ECC71', 'text': '#FFFFFF'},
}

def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def fetch_wikipedia_image(topic):
    try:
        search_url = "https://en.wikipedia.org/w/api.php"
        params = {'action':'query','list':'search','srsearch':topic,'srlimit':1,'format':'json'}
        r = requests.get(search_url, params=params, timeout=8)
        results = r.json().get('query',{}).get('search',[])
        if not results: return None
        page_title = results[0]['title']
        img_params = {'action':'query','titles':page_title,'prop':'pageimages','pithumbsize':600,'format':'json'}
        r2 = requests.get(search_url, params=img_params, timeout=8)
        pages = r2.json().get('query',{}).get('pages',{})
        for page in pages.values():
            thumb = page.get('thumbnail',{})
            if thumb.get('source'): return thumb['source']
    except Exception as e:
        print(f"[WIKI] {e}")
    return None

def generate_title_card(title, hook, channel, wikipedia_topic=None):
    """Generate a 1280x720 title card - Gentil Gedeon style"""
    W, H = 1280, 720
    colors = CHANNEL_COLORS.get(channel, CHANNEL_COLORS['news'])
    bg_color = hex_to_rgb(colors['bg'])
    accent_color = hex_to_rgb(colors['accent'])

    img = Image.new('RGB', (W, H), bg_color)
    draw = ImageDraw.Draw(img)

    # Try fetch Wikipedia/topic image
    topic_img = None
    if wikipedia_topic:
        img_url = fetch_wikipedia_image(wikipedia_topic)
        if img_url:
            try:
                r = requests.get(img_url, timeout=10)
                raw = Image.open(io.BytesIO(r.content)).convert('RGB')
                # Scale to fill right half
                iw, ih = raw.size
                ratio = H / ih
                nw = int(iw * ratio)
                raw = raw.resize((nw, H), Image.LANCZOS)
                # Darken the image slightly
                raw = ImageEnhance.Brightness(raw).enhance(0.75)
                paste_x = W // 2
                img.paste(raw, (paste_x, 0))
                topic_img = True
                print(f"[CARD] Topic image placed")
            except Exception as e:
                print(f"[CARD IMG] {e}")

    # Dark gradient overlay left side for text readability
    for x in range(W):
        # Full dark on left, fade to transparent on right
        if x < W // 2:
            alpha = 220
        else:
            alpha = max(0, int(220 * (1 - (x - W//2) / (W//2))))
        for y in range(0, H, 4):
            try:
                px = img.getpixel((x, y))
                blended = tuple(int(bg_color[i]*(alpha/255) + px[i]*(1-alpha/255)) for i in range(3))
                for dy in range(4):
                    if y+dy < H:
                        img.putpixel((x, y+dy), blended)
            except: pass

    # Load fonts
    try:
        font_huge  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 88)
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 68)
        font_med   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 42)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
        font_brand = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
    except:
        font_huge = font_large = font_med = font_small = font_brand = ImageFont.load_default()

    # Left accent bar
    draw.rectangle([(0,0),(10,H)], fill=accent_color)

    # Channel tag top left
    ch_name = channel.upper()
    draw.rectangle([(20,20),(20+len(ch_name)*18+20, 60)], fill=accent_color)
    draw.text((30, 28), ch_name, font=font_small, fill=(0,0,0))

    # DOCTOR SHEMA brand
    draw.text((22, 72), "DOCTOR SHEMA", font=font_small, fill=accent_color)

    # Main title - wrap at 18 chars, max 3 lines
    words = title.upper().split()
    lines = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        if len(test) <= 18:
            current = test
        else:
            if current: lines.append(current)
            current = word
    if current: lines.append(current)
    lines = lines[:3]

    # Choose font size based on line length
    title_font = font_large if max((len(l) for l in lines), default=0) > 12 else font_huge

    y_title = 120
    for line in lines:
        # Black shadow
        draw.text((26, y_title+4), line, font=title_font, fill=(0,0,0))
        draw.text((24, y_title+2), line, font=title_font, fill=(0,0,0))
        # White text
        draw.text((22, y_title), line, font=title_font, fill=(255,255,255))
        y_title += int(title_font.size * 1.15)

    # Hook text in accent color
    if hook:
        hook_short = hook[:100]
        hook_lines = textwrap.wrap(hook_short, width=30)[:2]
        y_hook = y_title + 15
        for hl in hook_lines:
            draw.text((24, y_hook+2), hl, font=font_med, fill=(0,0,0))
            draw.text((22, y_hook), hl, font=font_med, fill=accent_color)
            y_hook += 52

    # Bottom bar
    draw.rectangle([(0, H-55),(W, H)], fill=accent_color)
    draw.text((20, H-40), "DOCTOR SHEMA  |  @drshemaaa  |  SUBSCRIBE FOR MORE", font=font_brand, fill=(0,0,0))

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=92)
    return buf.getvalue()

def generate_thumbnail_b64(title, hook, channel, wikipedia_topic=None):
    try:
        data = generate_title_card(title, hook, channel, wikipedia_topic)
        return base64.b64encode(data).decode()
    except Exception as e:
        print(f"[THUMB] {e}")
        return None

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

def create_title_card_video(title_card_bytes, tmpdir, duration=3):
    """Turn the title card image into a 3-second video clip"""
    img_path = os.path.join(tmpdir, 'title_card.jpg')
    tc_video = os.path.join(tmpdir, 'title_card.mp4')
    with open(img_path, 'wb') as f:
        f.write(title_card_bytes)
    result = subprocess.run([
        'ffmpeg','-y',
        '-loop','1','-i',img_path,
        '-t',str(duration),
        '-vf','scale=320:180,setsar=1',
        '-r','20','-an',
        '-c:v','libx264','-preset','ultrafast','-b:v','120k',
        tc_video
    ], capture_output=True, timeout=30)
    if os.path.exists(tc_video) and os.path.getsize(tc_video) > 0:
        print(f"[CARD] Title card video created: {duration}s")
        return tc_video
    print(f"[CARD] Failed: {result.stderr.decode()[:200]}")
    return None

@app.route('/build',methods=['POST'])
def build_video():
    try:
        data=request.get_json()
        script=data.get('script',''); title=data.get('title','video')
        c1=data.get('clip1_url',''); c2=data.get('clip2_url',''); c3=data.get('clip3_url','')
        channel=data.get('channel','news')
        hook=data.get('hook','')
        wikipedia_topic=data.get('wikipedia_topic','')
        print(f"[BUILD] {title[:60]}")

        # Generate title card image
        title_card_bytes = None
        thumb_b64 = None
        try:
            title_card_bytes = generate_title_card(title, hook, channel, wikipedia_topic)
            thumb_b64 = base64.b64encode(title_card_bytes).decode()
            print(f"[CARD] Generated OK ({len(title_card_bytes)//1024}KB)")
        except Exception as te:
            print(f"[CARD] Failed: {te}")

        with tempfile.TemporaryDirectory() as tmp:
            ap,sp=gen_audio(script,tmp)
            if not ap: return jsonify({'success':False,'error':'TTS failed'}),500

            has_srt=sp and os.path.exists(sp) and os.path.getsize(sp)>10
            r=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration',
                '-of','default=noprint_wrappers=1:nokey=1',ap],capture_output=True,text=True)
            dur=min(float(r.stdout.strip() or '45'),240)

            # Create title card video (3 seconds)
            tc_video = None
            if title_card_bytes:
                tc_video = create_title_card_video(title_card_bytes, tmp, duration=3)

            # Download and process stock clips
            urls=[u for u in [c1,c2,c3] if u]
            # Reduce duration by 3s since title card takes first 3s
            content_dur = max(dur - 3, dur)
            cdur=content_dur/max(len(urls),1)
            procs=[]
            for i,u in enumerate(urls):
                raw=os.path.join(tmp,f'r{i}.mp4'); out=os.path.join(tmp,f'p{i}.mp4')
                try:
                    dl(u,raw)
                    if loop_clip(raw,cdur,out,i): procs.append(out)
                except Exception as e: print(f"[CLIP {i}] {e}")

            if not procs: return jsonify({'success':False,'error':'No clips'}),500

            # Concatenate content clips
            lst=os.path.join(tmp,'l.txt')
            with open(lst,'w') as f:
                for p in procs: f.write(f"file '{p}'\n")
            cat=os.path.join(tmp,'cat.mp4')
            subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i',lst,'-c','copy',cat],capture_output=True)

            # Prepend title card to content
            final_cat = os.path.join(tmp, 'with_card.mp4')
            if tc_video and os.path.exists(tc_video):
                combo_lst = os.path.join(tmp, 'combo.txt')
                with open(combo_lst, 'w') as f:
                    f.write(f"file '{tc_video}'\n")
                    f.write(f"file '{cat}'\n")
                subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i',combo_lst,
                    '-c','copy', final_cat], capture_output=True)
                if not os.path.exists(final_cat) or os.path.getsize(final_cat)==0:
                    final_cat = cat  # fallback
            else:
                final_cat = cat

            # Add audio + captions
            fin=os.path.join(tmp,'final.mp4')
            if has_srt:
                se=sp.replace('\\','/').replace(':','\\:')
                vf=(f"scale=320:180,subtitles='{se}':force_style='"
                    f"FontName=Arial,FontSize=14,Bold=1,PrimaryColour=&H00FFFFFF,"
                    f"OutlineColour=&H00000000,Outline=2,Alignment=2,MarginV=10'")
                r2=subprocess.run(['ffmpeg','-y','-i',final_cat,'-i',ap,
                    '-map','0:v:0','-map','1:a:0','-vf',vf,
                    '-c:v','libx264','-preset','ultrafast','-b:v','120k',
                    '-c:a','aac','-b:a','48k','-shortest',fin],capture_output=True,timeout=300)
                if r2.returncode!=0:
                    subprocess.run(['ffmpeg','-y','-i',final_cat,'-i',ap,
                        '-map','0:v:0','-map','1:a:0','-vf','scale=320:180',
                        '-c:v','libx264','-preset','ultrafast','-b:v','100k',
                        '-c:a','aac','-b:a','48k','-shortest',fin],capture_output=True)
            else:
                subprocess.run(['ffmpeg','-y','-i',final_cat,'-i',ap,
                    '-map','0:v:0','-map','1:a:0','-vf','scale=320:180',
                    '-c:v','libx264','-preset','ultrafast','-b:v','100k',
                    '-c:a','aac','-b:a','48k','-shortest',fin],capture_output=True)

            if not os.path.exists(fin) or os.path.getsize(fin)==0:
                return jsonify({'success':False,'error':'Final render failed'}),500

            sz=os.path.getsize(fin)
            print(f"[BUILD] Done: {sz/1024/1024:.1f}MB, title_card={'yes' if tc_video else 'no'}")
            with open(fin,'rb') as f: vb64=base64.b64encode(f.read()).decode()

            return jsonify({
                'success':True,'has_audio':True,'has_captions':has_srt,
                'has_title_card': tc_video is not None,
                'has_thumbnail': thumb_b64 is not None,
                'thumbnail': thumb_b64,
                'file_size':sz,'duration':round(dur,1),
                'title':title,'video':vb64
            })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success':False,'error':str(e)}),500

@app.route('/health',methods=['GET'])
def health():
    return jsonify({'status':'ok','voice':VOICE,'quality':'320x180','title_card':'enabled','thumbnail':'enabled'})

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))

from flask import Flask, request, jsonify
import subprocess, tempfile, os, requests, asyncio, traceback, base64

app = Flask(__name__)
VOICE = "en-US-ChristopherNeural"

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
        print(f"[BUILD] {title[:50]}")
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
                'has_thumbnail':False,'file_size':sz,'duration':round(dur,1),
                'title':title,'video':vb64})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success':False,'error':str(e)}),500

@app.route('/health',methods=['GET'])
def health():
    return jsonify({'status':'ok','voice':VOICE,'quality':'320x180 small'})

if __name__=='__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))

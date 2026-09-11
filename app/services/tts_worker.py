"""Warm local Qwen service. Model/voice features survive requests; GPU work is serialized."""
import json,os,sys,time,threading,subprocess,secrets
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[2]
STATE=ROOT/'uploads/tts-service';PORT=9019

def auth():
    STATE.mkdir(parents=True,exist_ok=True);p=STATE/'token'
    try:
        with p.open('x') as f:f.write(secrets.token_urlsafe(32))
    except FileExistsError:pass
    return p.read_text().strip()

def launch(python):
    from app.services.qwen_policy import require_enabled
    require_enabled()
    # Short-lived launcher prevents web-server tree shutdown from killing the service.
    subprocess.run([str(python),'-m','app.services.tts_worker','launch'],cwd=ROOT,
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=15)

def serve():
    from app.services.qwen_policy import require_enabled
    require_enabled()
    lock=threading.Lock();models={};prompts={};key=auth()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,data):
            encoded=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
        def do_GET(self):self.reply(200,{'ok':True,'service':'dan-tts','pid':os.getpid()})
        def do_POST(self):
            if self.headers.get('Authorization')!='Bearer '+key:return self.reply(401,{'ok':False})
            try:
                data=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
                with lock:
                    from app.services.gpu_lock import GpuLock
                    import torch,soundfile as sf
                    from qwen_tts import Qwen3TTSModel
                    profile=Path(data['profile']);prof=json.loads((profile/'profile.json').read_text(encoding='utf-8'))
                    name=prof.get('model') or 'Qwen/Qwen3-TTS-12Hz-1.7B-Base'
                    t=time.monotonic();files={}
                    with GpuLock(label='tts-warm') as gpu:
                        model=models.get(name)
                        if model is None:
                            model=Qwen3TTSModel.from_pretrained(name,device_map='cuda:0',dtype=torch.bfloat16,attn_implementation='sdpa');models[name]=model
                        else:model.model.to('cuda:0')
                        try:
                            ref=profile/(prof.get('ref_audio') or 'ref.wav')
                            prompt_key=(str(profile),ref.stat().st_mtime,(profile/'profile.json').stat().st_mtime)
                            prompt=prompts.get(prompt_key)
                            if prompt is None:
                                prompt=model.create_voice_clone_prompt(ref_audio=str(ref),ref_text=prof.get('ref_text',''));prompts[prompt_key]=prompt
                            for label,text in data['lines'].items():
                                wavs,sr=model.generate_voice_clone(text=text,language=prof.get('language','Japanese'),voice_clone_prompt=prompt)
                                dest=Path(data['out_dir'])/(label+'.wav');dest.parent.mkdir(parents=True,exist_ok=True);sf.write(str(dest),wavs[0],sr)
                                files[label]={'path':str(dest),'duration':len(wavs[0])/sr,'spoken':text}
                        finally:
                            # Retain weights in RAM, free VRAM for SAM/other local GPU work.
                            model.model.to('cpu');torch.cuda.empty_cache()
                    result={'ok':True,'files':files,'seconds':round(time.monotonic()-t,2),'gpu_wait':gpu.waited,'warm_service':True}
                self.reply(200,result)
            except Exception as exc:self.reply(500,{'ok':False,'error':str(exc)})
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()

if __name__=='__main__':
    from app.services.qwen_policy import require_enabled
    require_enabled()
    if len(sys.argv)>1 and sys.argv[1]=='launch':
        STATE.mkdir(parents=True,exist_ok=True)
        with (STATE/'service.log').open('ab') as log:
            subprocess.Popen([sys.executable,'-m','app.services.tts_worker','serve'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,close_fds=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=os.name!='nt')
    else:serve()

"""Two explicitly authorized Google-direct generations. No Higgsfield dependency."""
import base64,hashlib,json,subprocess,time
from pathlib import Path
import httpx
from app.config import settings
from app.services.timeline_captions import _ffmpeg

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'exports/omni-direct-comparison';OUT.mkdir(parents=True,exist_ok=True)
MODEL='gemini-omni-1.1-flash'
ENDPOINT='https://generativelanguage.googleapis.com/v1beta/interactions'
draft=ROOT/'uploads/production-assets/collage-acceptance-2db12005/agent_c8e1a518a03f.mp4'
reference=ROOT/'uploads/production-assets/2c1c50e1-61c4-44eb-99e5-8f78905ab200/assistant/references/b9dafbc0449c88c6a3767025.mp4'
ref_input=OUT/'reference-input-3s.mp4'
if not ref_input.exists():
    # A disposable API upload excerpt, not an editor source or replacement.
    subprocess.run([_ffmpeg(),'-nostdin','-y','-loglevel','error','-ss','0','-i',str(reference),'-t','3','-an',
                    '-c:v','libx264','-preset','fast','-crf','18',str(ref_input)],check=True,
                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

common='''Create a 5-second, landscape 16:9, polished editorial sports collage about an imagined future World Cup match in which Japan defeats Brazil. The tiny story is: focused Japanese player, decisive attacking play, goal, Japanese celebration. The result should feel like professionally art-directed kinetic photographic collage: tactile paper, real photographic detail, expressive moving cutouts, foreground overlaps, varied scale, motivated rapid camera pushes and transitions, cream and charcoal with yellow and red accents. The subjects and action should feel alive rather than merely swapping flat photographs. Keep the imagery legible and the scene progression clear. Sound: concise paper-swish accents and stadium atmosphere, no narration. This is a fictional creative concept. Make one short finished video, not multiple alternatives.'''
cases=[
 ('a_from_draft',draft,'[# Sources <VIDEO_0>@Video1] '+common+' Use Video1 as the draft to finish. Keep its subject order and approximate composition/timing, but upgrade the flat photo movements, visual integration, dimensionality and transitions into a finished professional collage. Preserve the Japan-versus-Brazil story.'),
 ('b_from_reference',ref_input,'[# References <VIDEO_REF_0>@Video1] '+common+' Use Video1 only as a visual-style and motion-design reference, not as a source video to edit. Invent the football imagery and compositions for the new story. Do not reproduce the eyes, envelopes, detective imagery or original topic from the reference. Transfer its layered collage construction, visual density and dynamic transitions to the football story.')
]

def metadata(value):
    if isinstance(value,list):return [metadata(v) for v in value]
    if isinstance(value,dict):return {k:('[media omitted]' if k=='data' else metadata(v)) for k,v in value.items()}
    return value

for name,media,prompt in cases:
    output=OUT/(name+'.mp4');receipt=OUT/(name+'.response.json');request_file=OUT/(name+'.request.json')
    if output.exists():
        print(name,'already generated; reusing',flush=True);continue
    if receipt.exists():
        raise RuntimeError(name+': prior response exists without a video; inspect it before repeating a paid request')
    request={'model':MODEL,'input':[{'type':'video','mime_type':'video/mp4','data':base64.b64encode(media.read_bytes()).decode()},
                                  {'type':'text','text':prompt}],
             'response_format':{'type':'video','aspect_ratio':'16:9','resolution':'720p'},
             'background':False,'store':False,'stream':False}
    request_file.write_text(json.dumps({'endpoint':ENDPOINT,'model':MODEL,'input_path':str(media),
        'input_sha256':hashlib.sha256(media.read_bytes()).hexdigest(),'prompt':prompt,
        'response_format':request['response_format'],'requested_seconds':5},ensure_ascii=False,indent=2),encoding='utf-8')
    print(name,'requesting Google directly',flush=True);start=time.monotonic()
    response=httpx.post(ENDPOINT,headers={'x-goog-api-key':settings.GOOGLE_GEMINI_API_KEY},json=request,timeout=600)
    try:data=response.json()
    except ValueError:data={'error':'Non-JSON response','status_code':response.status_code}
    record={'http_status':response.status_code,'elapsed_seconds':round(time.monotonic()-start,2),'response':metadata(data)}
    receipt.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    if response.status_code!=200:
        print(name,'ERROR',response.status_code,json.dumps(metadata(data),ensure_ascii=False)[:1500],flush=True)
        raise SystemExit(1)
    blocks=[c for step in data.get('steps',[]) if step.get('type')=='model_output' for c in step.get('content',[])]
    blocks+=data.get('outputs',[])
    videos=[v for v in blocks if v.get('type')=='video']
    if not videos and isinstance(data.get('output_video'),dict):videos=[data['output_video']]
    if len(videos)!=1:raise RuntimeError('Expected exactly one video; inspect '+str(receipt))
    video=videos[0]
    if video.get('data'):output.write_bytes(base64.b64decode(video['data']))
    elif video.get('uri'):
        from urllib.parse import urlparse
        uri=video['uri']
        if urlparse(uri).hostname!='generativelanguage.googleapis.com':raise RuntimeError('Unexpected download host')
        download=httpx.get(uri,headers={'x-goog-api-key':settings.GOOGLE_GEMINI_API_KEY},timeout=120)
        download.raise_for_status();output.write_bytes(download.content)
    else:raise RuntimeError('Video has no downloadable content')
    print(name,'SAVED',str(output),'seconds',record['elapsed_seconds'],'usage',data.get('usage'),flush=True)

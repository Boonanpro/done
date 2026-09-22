"""Compare the same failed-test narration on the provisioned cloud GPU (no cache)."""
import json
import time
from pathlib import Path
from app.services import cloud_speech as cloud, timeline_speech as speech

cfg=json.loads(cloud.CONFIG.read_text(encoding='utf-8'))
out=speech.ROOT/'uploads/cloud-speech-benchmark';out.mkdir(exist_ok=True)
events=speech.ROOT/'uploads/production-assets/a3970e0b-f7dc-472e-ad63-e8c51382ddb3/jobs/204f0b9d-01fb-4f31-a1df-82b88f418eab/events.jsonl'
rows=[json.loads(l) for l in events.read_text(encoding='utf-8').splitlines()]
original=next(r['input']['text'] for r in rows if r.get('name')=='mcp__timeline__generate_speech')
results=[]
ssh=cloud.connect(cfg)
try:
    with ssh.open_sftp() as sftp:
        deadline=time.monotonic()+600
        while True:
            try:
                with sftp.open(cloud.REMOTE+'/uploads/tts-service/install.exit') as f:
                    assert f.read().strip()==b'0','Cloud dependencies failed to install'
                break
            except FileNotFoundError:
                if time.monotonic()>deadline:raise TimeoutError('Cloud installation')
                time.sleep(5)
finally:ssh.close()
print('Dependencies ready; cloud benchmark starts',flush=True)
for name,text in [('warmup','必要な情報を送ってください。'),('same_long_text',original)]:
    start=time.monotonic()
    result=cloud.synthesize(cfg,speech.VOICE_ROOT/'owner',{name:speech.spoken_form(text)},out,timeout=600)
    result['wall_seconds']=round(time.monotonic()-start,2)
    result['test']=name
    results.append(result)
    (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
    assert result.get('ok'),result

"""Final, production-server acceptance cohort; each case gets a new empty room."""
import json,os,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CASES=[('caption','audio-phrases.json','ec6dcb660f83'),
       ('motion','motion-phrases.json','hf-code-particle-assemble'),
       ('film','film-phrases.json','film-sintel-dialogue')]

def main():
    output=os.environ.get('DAN_ACCEPTANCE_OUTPUT','visual-acceptance-final')
    base=os.environ.get('DAN_TEST_BASE','http://127.0.0.1:8000')
    cases=CASES+([('lifestyle','lifestyle-phrases.json','stock-car')] if os.environ.get('DAN_ACCEPTANCE_LIFESTYLE')=='1' else [])
    out=ROOT/'scratch'/output;out.mkdir(parents=True,exist_ok=True)
    if (out/'results.json').exists():
        raise RuntimeError('Choose a new DAN_ACCEPTANCE_OUTPUT; preserve earlier evidence.')
    # Expected endpoints are evaluation data, never sent to Dan.
    (out/'expectations.json').write_text(json.dumps(cases,indent=2),encoding='utf8')
    results=[]
    for name,phrases,target in cases:
        folder=output+'/'+name
        env={**os.environ,'DAN_TEST_BASE':base,'DAN_TEST_OUTPUT':folder,
             'DAN_TEST_PHRASES':str(ROOT/'scratch/visual-decision'/phrases)}
        subprocess.run([sys.executable,'-X','utf8','scratch/visual_voice_acceptance.py'],env=env,cwd=ROOT,check=True)
        subprocess.run([sys.executable,'-X','utf8','scripts/summarize_visual_audio_trial.py','scratch/'+folder],cwd=ROOT,check=True)
        data=json.loads((ROOT/'scratch'/folder/'final.json').read_text(encoding='utf8'))
        results.append({'case':name,'target_in_final_examples':any(i.get('library_id')==target for i in data['presentations'][-1]['items']),
            'measurement':json.loads((ROOT/'scratch'/folder/'measurement.json').read_text(encoding='utf8'))})
        (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps([{k:v for k,v in r.items() if k!='measurement'} for r in results]))

if __name__=='__main__':main()

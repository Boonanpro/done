"""Real Live audio trials of the shared end gate; isolated from phone and rooms."""
import asyncio
import json
from types import SimpleNamespace
from scripts import voice_conversation_trial as trial
from scripts.report_voice_latency import trailing_silence

PHRASES = [
 '電話を切ってください', '通話を終了してください', 'この会話を終わらせてください',
 'じゃあ、電話切って', 'ありがとう、通話を終わりにして', 'この電話を切って',
 '今の通話を終了して', '会話を終了して', '電話を終わらせて', '通話を切ってください',
 'もう、電話を切ってよ', 'では、会話を終わりにしてください', '一旦、通話を終了して',
 'はい、電話切ってください', '了解、通話を終わらせて', '電話を終了して',
 'この通話を終わりにして', '今の会話を終わらせて', 'じゃあ、会話を終了してください',
 'ありがとう。電話を切ってください。',
]

async def main():
 rows=[]
 for index, text in enumerate(PHRASES):
  name=f'end_acceptance_{index:02d}'
  label=name+'-result'
  trial.PHRASES[name]=text
  args=SimpleNamespace(cases=name,wait=8,label=label,interject=None,deployed=None,
                       suppress_followup_delegation=False,speech_instructions=None,local_end_gate=True)
  try:
   await trial.run(args)
   events=json.loads((trial.OUT/(label+'.json')).read_text(encoding='utf-8'))
   ended=next((e for e in events if e.get('kind')=='input_end'),None)
   closed=next((e for e in events if e.get('type')=='call_closed'),None)
   silence=trailing_silence(trial.OUT/(name+'.wav'))
   latency=round(closed['at']-ended['at']+silence,3) if ended and closed and silence is not None else None
   rows.append({'case':name,'source':closed.get('source') if closed else None,
                'estimated_speech_end_to_close_s':latency,'within_2s':latency is not None and 0<=latency<=2})
  except Exception as error:
   rows.append({'case':name,'error':type(error).__name__,'within_2s':False})
  result={'scope':'synthetic desktop audio; not handset acceptance; explicit phrase corpus',
          'attempts':len(rows),'passed':sum(row['within_2s'] for row in rows),'rows':rows}
  (trial.OUT/'call-end-batch-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
  print(json.dumps({'batch_result':rows[-1]}),flush=True)

if __name__=='__main__':asyncio.run(main())

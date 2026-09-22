import json
from pathlib import Path
from app.services.video_analyzer import _analyze_file_sync

coffee=Path('uploads/production-assets/assistant-complete-test-8e96bdba')
acceptance=json.loads((coffee/'acceptance.json').read_text(encoding='utf-8'))
tasks=[(Path(acceptance['export']['result']['output_path']),coffee/'export-review.txt',
        '朝の珈琲店の静かな映画調の動画です。音声を聞き、字幕と発話のずれ、黒い余白、不自然な画像、カット切替、音声の速さを時刻つきで検品してください。単なる要約ではなく良い点と問題点を具体的に。')]
room=Path('uploads/production-assets/yoshikawa-repair-4e31fca0')
for start,end in [(0,90),(90,180)]:
    record=json.loads((room/f'review-{start}-{end}.json').read_text(encoding='utf-8'))
    tasks.append((Path(record['file']),room/f'quality-{start}-{end}.txt',
        f'全編を音声込みで検品してください。このファイルは動画の{start}秒から{end}秒です。字幕と発話のずれ、同じ話の不自然な重複、絵と説明の食い違い、口の動きと声のずれ、黒い余白、番号の露出、広すぎるモザイクを相対時刻つきで指摘。内容要約だけでなく編集品質の具体的な問題を答えてください。'))
for video,dest,prompt in tasks:
    answer=_analyze_file_sync(str(video),prompt)
    dest.write_text(answer or '',encoding='utf-8')
    print(dest,answer,flush=True)

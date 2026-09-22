import json
from app.services import timeline_live as tl,timeline_draft as td
from app.api.production_asset_routes import _render_sequence_job
from app.services.video_analyzer import _analyze_file_sync

r='a3970e0b-f7dc-472e-ad63-e8c51382ddb3';cid='277f96d8-2609-43e9-ba18-bcf3ea37f576'
c,s=tl.live_sequence(r,cid)
folder=td._room_dir(r)/'recovery'/'final-review';folder.mkdir(parents=True,exist_ok=True)
old=tl.live_sequence(r,cid)[0].get('outputs')
result=_render_sequence_job(r,'final-reviewed-v9',cid,{'timeline':c['timeline'],'no_register':True},folder)
assert result and tl.live_sequence(r,cid)[0].get('outputs')==old
(folder/'export.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('RENDERED',result['output_path'],flush=True)
review=_analyze_file_sync(result['output_path'],'この3分の動画を最初から最後まで音声込みで検品してください。特に24〜34秒の部品画像と説明の対応、85.53〜86.23秒の銘板の隠し方、149.7秒以降の話と映像の重複、最後の挨拶が途中で切れていないか。字幕のサイズは本人指定なので変更指摘は不要です。時刻をつけ、実際の内容に基づいて答えてください。')
(folder/'quality.txt').write_text(review or '',encoding='utf-8')
print('REVIEW_SAVED',folder/'quality.txt',flush=True)

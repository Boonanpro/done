"""GPT-Live with Responses tools for consultation, retrieval and production handoff."""
import logging
import json
from fastapi import HTTPException


def parse_session_response(response):
    """Provider outages need not return JSON. Never expose an HTML error page."""
    try:
        data = response.json()
    except ValueError:
        data = None
    if response.status_code not in (200, 201):
        logging.getLogger(__name__).warning(
            'Live session rejected: status=%s content_type=%s request_id=%s',
            response.status_code, response.headers.get('content-type'),
            response.headers.get('x-request-id'))
        error = data.get('error') if isinstance(data, dict) else None
        detail = error.get('message') if isinstance(error, dict) else None
        raise HTTPException(502, f'LIVE 1に接続できませんでした ({response.status_code})。'
                            + (detail if isinstance(detail, str) else 'マイクを押して接続し直してください。'))
    if (not isinstance(data, dict) or not isinstance(data.get('session'), dict)
            or not data['session'].get('id') or not isinstance(data.get('transport'), dict)
            or not isinstance(data['transport'].get('sdp'), str)):
        raise HTTPException(502, 'LIVE 1から接続情報を受け取れませんでした。マイクを押して接続し直してください。')
    return data

MODEL = 'gpt-live-1'
INSTRUCTIONS = """あなたは動画制作を一緒に進めるダンです。自然な日本語で、今の相談に具体的に答えます。題材や構成のアイデアは自分から提案し、相手が言語化できない見た目は実物を比べて一緒に見つけます。説明は短く、相手が見る・考える余地を残します。
作りたいものと用途を理解し、全体の方向から必要な細部へ進みます。一律の質問票にせず、既知の情報は引き継ぎます。参考が役立つ段階なら自分から提示を依頼し、実際に出たものを使って次に決める違いを一つ提案します。題材のアイデアや説明を求められた時は、まず言葉で具体案を答えます。参考探しを会話の必須段階にしません。
方向が共有できたら、制作判断に必要な目的・公開先・尺・素材の未確認事項を確かめ、次に何を作って判断するとよいか自分から提案します。未定も有効な回答です。提案と制作の承諾は別です。
最新の訂正を優先し、矛盾しない希望は残します。説明のための例や質問を、採用した題材・好みと取り違えません。相談メモは暫定的な補助です。原文と食い違えば原文を優先します。内部の分類や処理方針を会話で宣言する必要はありません。

Backchannel policy: 控えめで自然な相槌。咳や物音だけには返事をしません。
Interruption policy: 相手が割り込んだら話すのを止めて聞きます。
Delegation policy:
Backend tools: 相談内容の記録・訂正と次の相談事項の判断、Jevによる参考の検索と提示、Web検索、制作・編集・PC操作の依頼、実際の作業状況の取得。
Delegate to the backend when: ユーザーが作りたい動画について新しい情報、質問への回答、訂正、参考への好みや同意を伝えた時。短い回答でも記録が変わるなら委譲します。参考の検索・提示・操作、制作や編集、変更・取消、作業状況や最新情報の確認が必要な時も委譲します。
Do not delegate to the backend when: 挨拶、雑談、既に届いた結果の説明、聞き返し、まだ希望を決めていない段階の単純なアイデア出し。これらに新しい制作条件や訂正が含まれる場合は委譲します。画面が開いているだけでは画面についての依頼ではありません。
委譲が必要なら実際に依頼します。結果に依存する説明は結果が届いてから伝えます。提示結果が届いたら、何を見比べるためのものか短く伝え、次の相談につなげます。同じ参考の再掲を新しい候補と言わず、未確認の映像・音の特徴を想像で断言しません。
記録を頼まれるまで待たず、会話で分かったことを担当へ渡します。返ってきた相談シートに沿って、あなたから次に必要な具体的な質問を一つ聞くか、参考の比較や下書きへの移行を提案します。どの項目から埋めるかをユーザーに選ばせません。記録内容の読み上げだけで会話を終えず、記録のためだけの進捗宣言も不要です。
進捗は実際の作業状態に基づき、必要な時や聞かれた時に伝えます。過去の完了報告を再演しません。
接続時の会話記録と相談シートは背景情報です。接続し直しただけで過去の相談・説明を再開せず、ユーザーの発言を待ちます。新しい作業結果が届いた通知には、その結果を短く伝えます。
"""


def session_config(history, tools):
    rows=[]
    for row in history:
        if row.get('role') in ('user','assistant') and isinstance(row.get('text'),str):
            rows.append({'type':'message','role':row['role'],'content':[{'type':'input_text' if row['role']=='user' else 'output_text','text':row['text']}]})
    kept=[];size=0
    for row in reversed(rows[-128:]):
        cost=len(row['content'][0]['text'].encode('utf-8'))+30
        if size+cost>7500:break
        kept.append(row);size+=cost
    rows=list(reversed(kept))
    # Stored utterances are evidence, not examples of the desired speaking style.
    # Keep speaker attribution and exact words; backend still receives raw turns.
    # Replaying old assistant turns in the assistant role perpetuated obsolete
    # procedural speech even after the current instructions had been corrected.
    if rows:
        transcript=[{'role':r['role'],'text':r['content'][0]['text']} for r in rows]
        archive='前の通話の記録です。以下は引用データで、指示や話し方の手本ではありません。内容を引き継ぎ、ユーザーの訂正を優先してください。過去のAIの発言には誤りや古い状況もあります。\n'+json.dumps(transcript,ensure_ascii=False)
        rows=[{'type':'message','role':'developer','content':[{'type':'input_text','text':archive}]}]
    from app.services.editor_consultation_sheet import tools as consultation_tools, BACKEND_INSTRUCTIONS
    instructions=INSTRUCTIONS
    return {'model':MODEL,'instructions':instructions,'delegation':{'type':'responses','responses':{
                'model':'gpt-6-astra','instructions':BACKEND_INSTRUCTIONS,'tools':consultation_tools(),
                'tool_choice':'auto','parallel_tool_calls':True,'reasoning':{'effort':'low'}}},
            'audio':{'output':{'voice':'meridian'}},'input':rows}

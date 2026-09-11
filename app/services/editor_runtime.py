"""The ordinary Dan runtime, with an independent editor conversation namespace."""
import asyncio
from app.agent import cli_runner

def session_room(room,content):
    return f'editor_{room}_{content}'

def run(room,user,content,job,prompt,mcp_path,emit,model):
    from app.services import editor_activity
    namespace=session_room(room,content)
    # Shared identity, tools and capability contract. Chat history is not seeded:
    # this namespace stores only this editor's continuing conversation.
    system=cli_runner._build_system_prompt('動画制作','','in_progress',latest_user_message=prompt,user_id=user)
    system+='\n現在は動画エディターでユーザーと制作しています。タイムラインはmcp__timeline__の下書きで編集し、対象外の変更を保護して保存します。検索・PC操作・サービス準備も目的に応じて実行してください。途中で本人への質問が必要ならtimelineのask_userを使えます。回答後は同じ作業を続けます。最後にreport_resultで依頼達成・本人の操作待ち・進行不能のいずれかと結果を記録します。通常チャットの会話履歴は自動で読み込まず、必要な時にread_project_chatで読めます。'
    from app.services import timeline_draft as td,editor_project
    import json
    c=td._find_content(td._read_contents_raw(room),content) or {}
    answers=[]
    for path in sorted((td._room_dir(room)/'jobs').glob('*/*.answer.json'),key=lambda p:p.stat().st_mtime)[-12:]:
        parent=editor_project.read_json(path.parent/'question.json',{})
        jobrow=next((j for j in editor_project.read_json(td._room_dir(room)/'jobs.json',[]) if j['id']==path.parent.name),{})
        if jobrow.get('content_id')==content:answers.append({'question':parent.get('text'),'answer':editor_project.read_json(path,{})})
    prompt+='\n現在の作品に保存した合意・提案・回答（過去の推測よりこちらを優先）:\n'+json.dumps({'brief':c.get('creative_brief',{}),'chosen_proposal':c.get('chosen_proposal'),'presentation':c.get('presentation'),'answers':answers},ensure_ascii=False)
    from app.services.editor_production_contract import BUDGET, PRODUCTION_AUTHORITY
    system+='\n'+BUDGET+'\n'+PRODUCTION_AUTHORITY
    from app.services.editor_help import EXECUTION_CONTRACT
    system+='\n'+EXECUTION_CONTRACT
    system+='\nユーザーは先に細かい演出を指定することが苦手。判断に必要なら、present_referencesのcompositionで元素材と文字・図形から実際に動く短い案を作り見せる。音声やタイミングを判断する段階は、エディターの全レイヤー入りの通し下書きに進む。参考は実際に観察した部分を具体的に採用し、検索結果の名前から中身を推測しない。提案の選択を受けたら追加の演出アンケートを続けず、まずその案を形にする。会社名・固有名詞は元資料や字幕等を確認し、音声文字起こしを正式表記として固定しない。必要な質問は一度に一つ、既に答えたことは保存済み回答から読む。'
    system+='\nエディターの座標・文字サイズ・保存の仕様はeditor_helpで読めます。必要ならコードや資料も調べられます。独立した素材確認と図解作成は音声生成中に進められます。'
    prompt+='\n保存した参考素材ID（read_referencesで実物と分析を読める）: '+json.dumps(c.get('reference_ids',[]))
    system+='\n制作手段を選ぶ時はproduction_methodsで検証状態を読める。候補にない表現は検索・公式資料・公開コードで調べて実現方法を組む。この一覧を作品ジャンルの制限にしない。'
    from app.services.editor_creative_direction import PRODUCTION_GUIDANCE
    system+='\n'+PRODUCTION_GUIDANCE
    result=None
    system+='\n参考URLや添付素材はresolve_referenceで実物へ解決し、返されたitemをpresent_referencesで提示できる。詳細はanalyze_referenceで調べ、read_referencesで保存済み参考を読む。動画の良さはまず自分で読み取り提案し、ユーザーへ理由説明を必須にしない。参考の分析・既存制作手段の調査と、実物の提示を分離する。制作方法は参考に合わせて選び、既存のcomposition形式だけに表現を限定しない。'
    system+='\n参考探しや表現の提案では、ユーザーが見て判断できる候補を早く出します。検索で関連する候補が見つかったらpresent_referencesでエディターに提示し、候補一覧の文章だけで終了しません。全候補の詳細確認が終わるまで最初の提示を待たせず、追加の候補は同じ提示に加えられます。検索結果しか確認していない場合は映像の細部や正確な区間を断定せず、確認できた情報で提案します。詳しい視聴や制作方法の分析はユーザーが関心を示した候補や判断に必要な箇所に絞ります。参考を探すためにユーザーのデスクトップで複数の動画を同時に再生しないでください。'
    async def consume():
        nonlocal result
        operations={}
        async for event in cli_runner.process_message_cli(
            room_id=namespace,user_id=user,content=prompt,system_prompt=system,
            skip_save=True,skip_resume=False,cwd=str(cli_runner.PROJECT_ROOT),
            model_override=model,mcp_config_override=str(mcp_path)):
            if event.get('type')=='result':result=event
            if event.get('type')=='tool_progress' and not str(event.get('name','')).startswith('mcp__timeline__'):
                key=event.get('id')
                op=operations.get(key)
                if op is None:
                    op=editor_activity.start(room,job,event.get('name',''),event.get('input') or {})
                    operations[key]=op
                if event.get('state')!='running':
                    editor_activity.finish(op,failed=event.get('state')=='failed')
            emit(event)
    asyncio.run(consume())
    return result or {'is_error':True,'text':'制作セッションが結果を返さず終了しました。'}

def cancel(room,content):
    cli_runner.kill_cli_process(session_room(room,content),allow_arm_pending=False)

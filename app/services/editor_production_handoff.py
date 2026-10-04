"""Brief completion selects consultation knowledge, never starts generation."""
import hashlib
import json
from copy import deepcopy
from app.services.jev_decisions import Decisions

PLAYBOOKS = {
    'story': {
        'match': '人物と出来事を中心にした映画・短編・物語。実写もアニメも含む。',
        'next': '既存のfilm_planと会話の展開案を引き継ぐ。展開が未定なら考えている展開があるか聞き、なければ提案する。人物の役割と物語を一緒に詰め、必要な人物・場所の見た目を画像で確認しながら下書きに進む。',
        'source': 'docs/current/genhq-cinematic-lesson-review-20260925.md',
        'evidence': 'GenHQ講義とStoryboard Method確認済み。Dan向けに調整。'},
    'explanation': {
        'match': 'トーク・教育・解説。話や図で内容を理解してもらう作品。',
        'next': '既知の題材と目的から伝える結論と話の流れを提案する。未決の論点だけ相談し、合意した流れに台詞・図解・挿入映像を組む。',
        'source': 'Dan provisional playbook', 'evidence': 'GenHQの該当講義は未確認。暫定手順。'},
    'experience': {
        'match': 'Vlog・体験記・記録。実際の出来事や収録素材を中心に組み立てる作品。',
        'next': '渡された素材と体験を引き継ぎ、見せる体験と見せ場の並びを提案する。素材が不明なら何があるか聞く。架空の出来事を実体験として補わない。',
        'source': 'Dan provisional playbook', 'evidence': 'GenHQの該当講義は未確認。暫定手順。'},
    'launch': {
        'match': '商品やサービスのローンチ・広告。コピー、UI、ロゴやモーションで価値を伝える。',
        'next': '商品の価値と見せる順序を短いコピーと画面の具体案として提案する。既存素材を引き継ぎ、見た目や動きが判断しにくい箇所をビジュアルで示す。',
        'source': 'docs/current/genhq-dan-workflow-assessment-20260924.md; docs/production-methods.json',
        'evidence': 'GenHQはHyperframes紹介ページのみ確認。手順はDanの暫定設計。'},
    'custom': {
        'match': 'MV・抽象映像・複合形式など他の基本手順一つでは目的を扱えない作品。',
        'next': 'シートと会話から進め方を組み立て、最初に判断する内容とそれを見る具体物を一案提案する。工程の選択をユーザーに丸投げしない。',
        'source': 'Dan provisional playbook', 'evidence': '個別に設計する。講義で実証済みとは扱わない。'},
}

async def select(sheet, previous, user_id):
    result = deepcopy(sheet)
    if not sheet.get('ready_for_draft'):
        return result
    fingerprint = hashlib.sha256(json.dumps(sheet['fields'], sort_keys=True,
        ensure_ascii=False).encode()).hexdigest()
    old = (previous or {}).get('production_handoff', {})
    if old.get('fingerprint') == fingerprint:
        result['production_handoff'] = deepcopy(old)
        result['production_handoff']['new_selection'] = False
        return result
    async with Decisions(user_id, timeout=5, max_calls=1, enabled=True) as decision:
        response = await decision.choose({'brief': sheet['fields']}, {
            'workflow': {'type': 'choice',
                'instructions': '作品の中心に合う制作相談手順を選ぶ。アニメ・実写は表現方法であり物語か解説かとは別。制作許可は判断しない。',
                'criteria': {k: v['match'] for k, v in PLAYBOOKS.items()}}})
    handoff = {'fingerprint': fingerprint, 'new_selection': True,
               'elapsed_ms': response.get('elapsed_ms'), 'starts_production': False}
    if response.get('available'):
        answer = response['answers']['workflow']
        key = answer['choice']
        handoff.update(status='selected', selected_by='jev', workflow=key,
                       confidence=answer['confidence'], playbook=deepcopy(PLAYBOOKS[key]))
    else:
        handoff.update(status='needs_model_selection', selected_by=None,
                       reason=response.get('reason'), candidates=deepcopy(PLAYBOOKS))
    result['production_handoff'] = handoff
    return result

GUIDANCE = '''シート更新結果のproduction_handoffが次の制作相談への引き継ぎです。new_selection=trueなら選ばれたplaybookのnextを会話・film_planと合わせて使い、次の具体的な相談をこの応答で始めます。工程名の宣言や「どこから手をつけたい？」で止めません。既知の内容は引き継ぎます。needs_model_selectionなら候補から今回に適した進め方をあなたが判断します。new_selection=falseなら最初の案内を繰り返さず現在の相談を続けます。手順の選定は作品の承認でも本番生成の許可でもありません。後続工程を自動連鎖せず、ユーザーの反応を受けて進めます。'''

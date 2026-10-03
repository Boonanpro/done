"""Confirmation cards (owner, 2026-10-03): before an irreversible step (a purchase, a payment, a booking, publishing,
deleting, an account-security change) Dan shows what exactly will happen as a card; the owner presses one button. The
press reaches Dan as the owner's chat message (「承認: …」), so it is unambiguous which question the answer belongs to
(a bare 「うん」 in a moving conversation could be taken for another question's answer).

Kept in dan_proposals (type 'action', action_data.kind 'confirm'); the room shows `[確認: <id>]`, which the app draws."""
import json
import os
import uuid

CARD_PREFIX = '[確認: '

TOOL = {
    'name': 'confirm_card',
    'description': ('取り返しのつかない確定（購入・支払い・チャージ・予約・公開・削除・解約・アカウントの安全設定の変更・広告の出稿など）の直前に、'
                    '何がどうなるかを本人に見せて、ボタン1つで承認してもらうカードを出す。文章で「〜しますか」と聞く代わりに使う。'
                    'items には金額・対象・日時・支払い方法など、本人が判断に要る事実だけを並べる（推測を書かない）。'
                    '候補から1つ選んでもらう時は choices（例: 予約の便）。本人が押すと、その答えが本人の発言としてこの部屋に届くので、'
                    '届いてから確定する。出したらターンを終えて待つ。外部の相手への文面の確認は compose_message の送信案カードを使う。'),
    'input_schema': {'type': 'object', 'properties': {
        'title': {'type': 'string', 'description': '何の確定か（例: 「Amazon で USB-C ケーブルを購入」）'},
        'items': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'label': {'type': 'string'}, 'value': {'type': 'string'}}, 'required': ['label', 'value']},
            'description': '判断に要る事実（例: 金額 / ¥6,199、届け先 / 自宅、支払い / Amex 末尾2006）'},
        'choices': {'type': 'array', 'items': {'type': 'string'}, 'description': '候補から1つ選ぶ時だけ（最大6）'},
        'confirm_label': {'type': 'string', 'description': '承認ボタンの文字（例: 購入する・予約する・公開する）'},
    }, 'required': ['title', 'items', 'confirm_label'], 'additionalProperties': False},
}


async def tool(params):
    from app.services.supabase_client import get_supabase_client
    from app.services.room_log import append as append_room_log
    user_id = os.environ.get('DAN_USER_ID', '')
    room_id = os.environ.get('DAN_SESSION_ID', '')
    if not user_id or not room_id:
        return {'success': False, 'error': 'この部屋が分からない'}
    title = str(params.get('title') or '').strip()[:120]
    items = [{'label': str(i.get('label', ''))[:40], 'value': str(i.get('value', ''))[:300]} for i in (params.get('items') or [])][:12]
    choices = [str(c)[:120] for c in (params.get('choices') or [])][:6]
    confirm = str(params.get('confirm_label') or '承認する')[:20]
    if not title or not items:
        return {'success': False, 'error': 'title と items が要る'}
    card_id = str(uuid.uuid4())
    get_supabase_client().client.table('dan_proposals').insert({
        'id': card_id, 'user_id': user_id, 'type': 'action', 'title': title, 'status': 'pending',
        'content': '\n'.join(f"{i['label']}: {i['value']}" for i in items), 'source_room_id': room_id,
        'action_data': {'kind': 'confirm', 'items': items, 'choices': choices, 'confirm_label': confirm},
    }).execute()
    append_room_log(room_id, f'{CARD_PREFIX}{card_id}]', sender_type='ai', sender_id=None)
    return {'success': True, 'output': f'確認カードを出した（{card_id[:8]}）。本人が押すと「承認: …」か「やめる: …」がこの部屋に届く。届くまで確定しない。このターンはここで終える。'}

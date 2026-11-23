"""Confirmation cards (owner, 2026-10-03): before an irreversible step (a purchase, a payment, a booking, publishing,
deleting, an account-security change) Dan shows what exactly will happen as a card; the owner presses one button. The
press reaches Dan as the owner's chat message (「承認: …」), so it is unambiguous which question the answer belongs to
(a bare 「うん」 in a moving conversation could be taken for another question's answer).

Kept in dan_proposals (type 'action', action_data.kind 'confirm'); the room shows `[確認: <id>]`, which the app draws."""
from urllib.parse import urlsplit
import os
import uuid

CARD_PREFIX = '[確認: '

# Limits (owner, 2026-11-12: 「文字が多すぎてほとんど読んでない」「内部の状態は見せるな」): the card holds only what will
# happen — what, how much, to whom, paid how, when. Why it is asked, what failed and what was tried go nowhere on the card.
MAX_TITLE = 30
MAX_ITEMS = 4
MAX_LABEL = 8
MAX_VALUE = 30
MAX_CHOICES = 4
MAX_CHOICE = 24

TOOL = {
    'name': 'confirm_card',
    'description': ('払う・買う・チャージ・予約・公開・削除・解約・安全設定の変更・広告の出稿の直前に、実行される中身を短く見せて、'
                    'ボタン1つで承認してもらうカード。本人は数秒で読んで押す。'
                    'items は「これから起きること」だけを最大4行（金額・相手や入金先・支払い方法・日時など）。'
                    '1行は「支払い / 11.66ドル（税込）」の短さにする。聞く理由・失敗した経緯・試したこと・今の状態・各案の説明は書かない'
                    '（要るなら返事の本文に1文だけ）。候補から選ぶ時は choices に短い名前だけ（例:「法人デビット 末尾3666」）。'
                    '押された答えが選択と承認を兼ねる。出したらターンを終えて待つ。'
                    '本人が中身を自分の言葉で決めた時（「11ドルチャージして」・ダンが聞いた金額や候補に答えた）は、'
                    '確かめた事実がそれと食い違わなければカードを出さずに実行し、結果で伝える。'
                    '承認の後に金額・相手・日時・支払い方法が変わった時だけ、変わった所だけのカードを出し直す。'
                    '外部への文面は compose_message。'),
    'input_schema': {'type': 'object', 'properties': {
        'owner_reply': {'type': 'string', 'description': '本人から一緒に聞かれた質問への回答全文。本人の会話に保存される。質問も説明も無い時だけ空文字。'},
        'products': {'type': 'array', 'description': '商品を買う時は全品を指定する。各商品の販売ページで確かめた実物の写真と個別ページ。',
                     'items': {'type': 'object', 'properties': {
                         'name': {'type': 'string'}, 'url': {'type': 'string', 'description': '販売店の個別商品ページのHTTPS URL'},
                         'image_url': {'type': 'string', 'description': 'その商品の写真のHTTPS URL'},
                         'store_logo_url': {'type': 'string', 'description': '販売店の実際のロゴ画像のHTTPS URL'},
                     }, 'required': ['name', 'url', 'image_url'], 'additionalProperties': False}},
        'title': {'type': 'string', 'description': f'何をするか（{MAX_TITLE}字まで。例:「DeepSeek に11ドルをチャージ」）。括弧書きの補足を足さない'},
        'items': {'type': 'array', 'maxItems': MAX_ITEMS, 'items': {'type': 'object', 'properties': {
            'label': {'type': 'string', 'description': f'{MAX_LABEL}字まで（例: 支払い）'},
            'value': {'type': 'string', 'description': f'{MAX_VALUE}字まで（例: 11.66ドル（税込））'}}, 'required': ['label', 'value']},
            'description': f'これから起きることだけ。最大{MAX_ITEMS}行'},
        'choices': {'type': 'array', 'maxItems': MAX_CHOICES, 'items': {'type': 'string'},
                    'description': f'候補から1つ選ぶ時だけ。最大{MAX_CHOICES}つ、各{MAX_CHOICE}字まで。名前だけで説明を付けない'},
        'confirm_label': {'type': 'string', 'description': '承認ボタンの文字（例: 払う・購入する・予約する・公開する）'},
    }, 'required': ['title', 'items', 'confirm_label', 'owner_reply'], 'additionalProperties': False},
}


def _too_long(params):
    """What exceeds the card's limits, as one line Dan can act on; '' when it fits."""
    title = str(params.get('title') or '').strip()
    items = params.get('items') or []
    choices = params.get('choices') or []
    problems = []
    if len(title) > MAX_TITLE:
        problems.append(f'題が{len(title)}字（{MAX_TITLE}字まで）')
    if len(items) > MAX_ITEMS:
        problems.append(f'行が{len(items)}つ（{MAX_ITEMS}つまで）')
    for i in items:
        label, value = str(i.get('label', '')).strip(), str(i.get('value', '')).strip()
        if len(label) > MAX_LABEL:
            problems.append(f'「{label}」の名前が長い（{MAX_LABEL}字まで）')
        if len(value) > MAX_VALUE:
            problems.append(f'「{label}」の中身が{len(value)}字（{MAX_VALUE}字まで）')
    if len(choices) > MAX_CHOICES:
        problems.append(f'候補が{len(choices)}つ（{MAX_CHOICES}つまで）')
    for c in choices:
        if len(str(c).strip()) > MAX_CHOICE:
            problems.append(f'候補「{str(c)[:12]}…」が長い（{MAX_CHOICE}字まで）')
    return '、'.join(problems)


def _https(value):
    if not isinstance(value, str) or any(c.isspace() for c in value) or chr(92) in value:
        return False
    try:
        url = urlsplit(value)
        return url.scheme == 'https' and bool(url.hostname) and not url.username and not url.password
    except ValueError:
        return False


def _product_error(products, title, button):
    if not products and (button in {'購入する', '購入', '買う', '注文する', '注文', 'Buy', 'Buy now'}
                         or title.endswith(('を買う', 'を購入する', 'を注文する'))):
        return '購入する各商品の名前・個別商品ページ・実物の画像を products に入れてください。'
    if not isinstance(products, list):
        return 'products は商品の配列です。'
    for product in products:
        if (not isinstance(product, dict) or not str(product.get('name') or '').strip()
                or not _https(product.get('url')) or not _https(product.get('image_url'))
                or ('store_logo_url' in product and not _https(product['store_logo_url']))):
            return '各商品の名前とHTTPSの商品ページ・写真を確認してください。'
    return ''


async def tool(params):
    from app.services.supabase_client import get_supabase_client
    from app.services.room_log import append as append_room_log
    user_id = os.environ.get('DAN_USER_ID', '')
    room_id = os.environ.get('DAN_SESSION_ID', '')
    if not user_id or not room_id:
        return {'success': False, 'error': 'この部屋が分からない'}
    title = str(params.get('title') or '').strip()
    items = [{'label': str(i.get('label', '')).strip(), 'value': str(i.get('value', '')).strip()} for i in (params.get('items') or [])]
    choices = [str(c).strip() for c in (params.get('choices') or []) if str(c).strip()]
    confirm = str(params.get('confirm_label') or '承認する')[:12]
    if not title or not items:
        return {'success': False, 'error': 'title と items が要る'}
    too_long = _too_long(params)
    if too_long:
        return {'success': False, 'error': (f'カードが長すぎるので出していない: {too_long}。'
                                            'これから起きること（何を・いくら・どこへ・何で払うか・いつ）だけを短く書き直して、もう一度出す。'
                                            '理由・経緯・失敗・各案の説明はカードに書かない。')}
    products = params.get('products', [])
    error = _product_error(products, title, confirm)
    if error:
        return {'success': False, 'error': error}
    owner_reply = str(params.get('owner_reply') or '').strip()
    card_id = str(uuid.uuid4())
    get_supabase_client().client.table('dan_proposals').insert({
        'id': card_id, 'user_id': user_id, 'type': 'action', 'title': title, 'status': 'pending',
        'content': '\n'.join(f"{i['label']}: {i['value']}" for i in items), 'source_room_id': room_id,
        'action_data': {'kind': 'confirm', 'items': items, 'choices': choices, 'confirm_label': confirm, 'products': products},
    }).execute()
    if owner_reply:
        append_room_log(room_id, owner_reply, sender_type='ai', sender_id=None)
    append_room_log(room_id, f'{CARD_PREFIX}{card_id}]', sender_type='ai', sender_id=None)
    return {'success': True, 'output': f'確認カードを出した（{card_id[:8]}）。本人が押すと「承認: …」か「やめる: …」がこの部屋に届く。届くまで確定しない。本人から聞かれた質問の答えを owner_reply に含めなかった場合は最終回答で伝える。'}

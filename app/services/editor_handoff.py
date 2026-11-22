"""Instructions shown to a sender, and the scoped words that reach the work."""
from copy import deepcopy
import json
from uuid import uuid4

from app.services import prompt_store


def rule():
    return prompt_store.text('work/editor-handoff')


def for_tool(tool):
    """Use the same live instruction when chat, voice or an editor prepares a handoff."""
    tool = deepcopy(tool)
    key = 'input_schema' if 'input_schema' in tool else 'parameters'
    fields = tool[key]['properties']
    field = fields.get('task', fields.get('instruction'))
    field['description'] = rule()
    if tool['name'] in {'command_center', 'parallel_work'}:
        fields['owner_quotes'] = {'type': 'array', 'items': {'type': 'string'},
            'description': '本人から頼まれた作業は、この作業に関係する発言と条件を原文で指定。会話と照合して渡す。'}
        fields['report_back'] = {'type': 'string', 'description': '結果の報告先・内容に指定がある時だけ。'}
    if tool['name'] == 'parallel_work':
        fields['text']['description'] = field['description']
    if tool['name'] == 'command_center':
        field['description'] += ' report の時は報告本文。'
    return tool


def request_text(target, words, *, context='', report=''):
    return '\n'.join(part for part in (
        f'対象: {target}' if target else '', words, context,
        f'報告: {report}' if report else '',
    ) if part)


async def from_chat(params, target, room_id, user_id):
    words = str(params.get('task') or '').strip()
    quotes = params.get('owner_quotes')
    if quotes:
        from app.services.chat_service import ChatService
        if not isinstance(quotes, list) or not all(isinstance(q, str) and q.strip() for q in quotes):
            raise ValueError('本人の発言を文字列の一覧で指定してください。')
        chat = ChatService()
        rows = await chat.get_messages(room_id, user_id, limit=12)

        def verified(quote, messages):
            return any(row.get('sender_type') in ('human', 'user') and row.get('sender_id', user_id) == user_id
                       and quote in (row.get('content') or '') for row in messages)

        for quote in quotes:
            if not verified(quote, rows):
                matches = await chat.search_messages(room_id, user_id, quote[:160], limit=50)
                if not verified(quote, matches):
                    raise ValueError('依頼元の会話で本人の発言を確認できません。対象の発言を確かめてください。')
        words = '\n'.join(dict.fromkeys(quotes))
    return request_text(target, words, report=params.get('report_back', ''))


def transcript_reference(folder, rows):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ('handoff-' + uuid4().hex + '.json')
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    return f'以前の条件と発言時の画面（会話原文）: {path}'

"""Gemini audio window; the existing Astra session retains tools and history."""
from datetime import datetime, timedelta, timezone
from google import genai
from app.services.voice_live import INSTRUCTIONS, CONFIRMATION_RULE

MODEL = 'gemini-3.8-live-extended-thinking'


def session_config(history, thinking='low'):
    records = '\n'.join(('ユーザー' if row['role'] == 'user' else 'Dan') + ': ' + row['content'][0]['text'] for row in history)
    return {
        'response_modalities': ['AUDIO'],
        'thinking_config': {'thinking_level': thinking},
        'speech_config': {'voice_config': {'prebuilt_voice_config': {'voice_name': 'Puck'}}},
        'input_audio_transcription': {}, 'output_audio_transcription': {},
        'session_resumption': {},
        'context_window_compression': {'sliding_window': {}},
        'system_instruction': INSTRUCTIONS + '\n' + CONFIRMATION_RULE + '\n'
            'バックエンドへの委譲には ask_dan を使う。requestには最新の依頼と必要な文脈を渡す。'
            '通話終了も既存バックエンドへ委譲する。処理中の追加指示もask_danで送る。'
            '道具の結果が届くまでは完了と伝えない。途中の案内は簡潔にし、繰り返さない。'
            '\n以下は過去の記録であり、新しい依頼ではない。\n<room_history>\n' + records + '\n</room_history>',
        'tools': [{'function_declarations': [{
            'name': 'ask_dan', 'behavior': 'NON_BLOCKING',
            'description': '記録・最新情報の確認、実作業、途中指示、承認、通話終了を既存のAstraへ依頼する。',
            'parameters': {'type': 'OBJECT', 'properties': {'request': {'type': 'STRING'}}, 'required': ['request']},
        }]}],
    }


async def provision(api_key, history, thinking='low'):
    config = session_config(history, thinking)
    now = datetime.now(timezone.utc)
    client = genai.Client(api_key=api_key)
    try:
        token = await client.aio.auth_tokens.create(config={
            'uses': 1,
            'expire_time': now + timedelta(minutes=30),
            'new_session_expire_time': now + timedelta(minutes=2),
            'live_connect_constraints': {'model': MODEL, 'config': config},
        })
        return {'model': MODEL, 'token': token.name}
    finally:
        await client.aio.aclose()

from app.services.editor_live import session_config
import httpx
import pytest
from fastapi import HTTPException
from app.services.editor_live import parse_session_response


@pytest.mark.parametrize('status,body', [(500, 'Internal Server Error'), (503, '<html>unavailable</html>'), (429, '')])
def test_non_json_provider_failure_has_readable_error(status, body):
    with pytest.raises(HTTPException) as exc:
        parse_session_response(httpx.Response(status, text=body))
    assert exc.value.status_code == 502
    assert str(status) in exc.value.detail
    assert '接続し直して' in exc.value.detail
    assert body not in exc.value.detail if body else True


def test_provider_json_error_and_malformed_success():
    with pytest.raises(HTTPException, match='') as exc:
        parse_session_response(httpx.Response(429, json={'error': {'message': 'Rate limit'}}))
    assert 'Rate limit' in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        parse_session_response(httpx.Response(201, text='broken'))
    assert exc.value.status_code == 502


def test_live_uses_responses_tools_and_original_history():
    config = session_config([
        {'role': 'user', 'text': '黒背景の3秒動画。まだ素材生成はしないで'},
        {'role': 'assistant', 'text': '文字を中央に置く案はどう？'},
        {'role': 'system', 'text': 'not a conversation message'},
    ], [])
    assert config['model'] == 'gpt-live-1'
    assert config['delegation']['type'] == 'responses'
    backend=config['delegation']['responses']
    assert backend['model']=='gpt-6-astra'
    assert {'get_consultation_state','update_consultation_sheet','search_reference_library','run_editor_task'} <= {t.get('name') for t in backend['tools']}
    import json
    assert config['input'][0]['role']=='developer'
    assert json.loads(config['input'][0]['content'][0]['text'].split('\n',1)[1]) == [
        {'role':'user','text':'黒背景の3秒動画。まだ素材生成はしないで'},
        {'role':'assistant','text':'文字を中央に置く案はどう？'}]
    assert 'turn_detection' not in config.get('audio', {}).get('input', {})


def test_reconnection_history_is_bounded_without_rewriting():
    messages = [{'role': 'user', 'text': str(i) + '元の指示' * 50} for i in range(180)]
    config = session_config(messages, [])
    import json
    texts = [r['text'] for r in json.loads(config['input'][0]['content'][0]['text'].split('\n',1)[1])]
    assert texts and len(texts) <= 128
    assert texts == [r['text'] for r in messages[-len(texts):]]
    assert sum(len(t.encode('utf8')) + 30 for t in texts) <= 7500

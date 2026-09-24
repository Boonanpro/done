"""Past-record search (2026-09-24): the 9/21 report that answered 「9/18の新幹線はキャンセルできた？」 was pushed out by the
day's chatter about trains, and 「払い戻し」 was never searched."""
import asyncio

from app.services import voice_past


def test_spaced_words_are_kept_whole():
    assert '払い戻し' in voice_past.keywords('9月18日 新幹線 払い戻し', [{'role': 'user', 'text': 'x'}])


def test_a_rare_word_outweighs_a_common_one_and_the_newest_comes_first(monkeypatch):
    report = {'id': 'r', 'sender_type': 'ai', 'content': '【Doneからの報告】 9月18日の分は翌日に自動払い戻し。' + 'あ' * 900 + '結論', 'created_at': '2026-09-21T08:14'}
    chatter = [{'id': f'c{i}', 'sender_type': 'human', 'content': '新幹線 新幹線', 'created_at': f'2026-09-24T02:{i:02d}'} for i in range(30)]
    def search(user, word, since):
        if word == '9月18日':
            return [report], 3                     # few records: names the topic
        return chatter, 800                        # hundreds of records: says little
    monkeypatch.setattr(voice_past, '_search', search)
    found = asyncio.run(voice_past.gather('u', '9月18日 新幹線', [{'role': 'user', 'text': 'x'}]))
    texts = [r['text'] for r in found['records']]
    assert any(t.startswith('【Doneからの報告】') and t.endswith('結論') for t in texts)   # kept, and long enough to reach the end
    ats = [r['at'] for r in found['records']]
    assert ats == sorted(ats, reverse=True)

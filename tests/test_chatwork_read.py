"""chatwork_read: what a call and chat Dan read from the owner's Chatwork (no network here)."""
import asyncio

from app.services import chatwork_read


ME = {'account_id': 1, 'name': '本田 樹'}
ROOMS = [
    {'room_id': 10, 'type': 'group', 'name': 'おさる日報チャット', 'unread_num': 168, 'mention_num': 0, 'last_update_time': 2_000_000_300},
    {'room_id': 20, 'type': 'direct', 'name': '中村ひろき', 'unread_num': 0, 'mention_num': 0, 'last_update_time': 2_000_000_200},
    {'room_id': 30, 'type': 'direct', 'name': '古い人', 'unread_num': 0, 'mention_num': 0, 'last_update_time': 1_000_000_000},
]
MESSAGES = {
    10: [{'account': {'account_id': 5, 'name': '中村太郎'}, 'send_time': 2_000_000_100, 'body': 'おはようございます'},
         {'account': {'account_id': 6, 'name': '山田'}, 'send_time': 2_000_000_300, 'body': '日報です'}],
    20: [{'account': {'account_id': 7, 'name': '中村ひろき'}, 'send_time': 2_000_000_000,
          'body': '[To:1]本田さん\n用紙を作りました'},
         {'account': {'account_id': 7, 'name': '中村ひろき'}, 'send_time': 2_000_000_010,
          'body': '[info][title][dtext:file_uploaded][/title][download:22]血液検査.pdf (170 KB)[/download][/info]'},
         {'account': {'account_id': 1, 'name': '本田 樹'}, 'send_time': 2_000_000_200, 'body': '[rp aid=7 to=20-1]ありがとうございます'}],
}


def fake(monkeypatch, now=2_000_000_400):
    async def get(user_id, path, params=None):
        if path == '/me': return ME
        if path == '/rooms': return ROOMS
        return MESSAGES.get(int(path.split('/')[2]), [])
    monkeypatch.setattr(chatwork_read, '_get', get)
    monkeypatch.setattr(chatwork_read.time, 'time', lambda: now)


def test_named_person_finds_direct_room_first_and_their_group_posts(monkeypatch):
    fake(monkeypatch)
    found = asyncio.run(chatwork_read.read('u', who='中村さん'))
    assert [r['room'] for r in found['rooms']] == ['中村ひろき', 'おさる日報チャット']
    nakamura = found['rooms'][0]
    assert nakamura['replied_after'] is True
    assert [m['from'] for m in nakamura['messages']] == ['中村ひろき', '中村ひろき', '本人']
    assert nakamura['messages'][1]['text'] == '（ファイル: 血液検査.pdf (170 KB)）'
    assert nakamura['messages'][0]['text'].startswith('@本田さん')
    assert [m['text'] for m in found['rooms'][1]['messages']] == ['おはようございます']   # only what a 中村 wrote


def test_without_name_old_rooms_are_left_out_and_direct_rooms_come_first(monkeypatch):
    fake(monkeypatch)
    found = asyncio.run(chatwork_read.read('u'))
    assert [r['room'] for r in found['rooms']] == ['中村ひろき', 'おさる日報チャット']
    text = chatwork_read.spoken_digest(found)
    assert '中村ひろき（1対1' in text and '本人が最後に返信済み' in text and '未読168' in text


def test_unknown_name_says_so_with_the_room_list(monkeypatch):
    fake(monkeypatch)
    found = asyncio.run(chatwork_read.read('u', who='佐藤'))
    assert found['rooms'] == [] and '佐藤' in found['note'] and '中村ひろき' in found['note']

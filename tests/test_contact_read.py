"""contact_read / line_notices / voice_router.named_person: 「〇〇さんから連絡来てる？」 across mail and LINE (no network here).

The notification fixture is the Galaxy's real `dumpsys notification --noredact` output of 2026-11-13 (LINE records and one
other app), with names and texts replaced."""
import asyncio
import email
import json
from datetime import datetime
from pathlib import Path

from app.services import contact_read, line_notices
from app.services.voice_router import named_person

DUMP = (Path(__file__).parent/'fixtures'/'line_notifications_dump.txt').read_text(encoding='utf-8')


def test_line_messages_are_read_from_the_notifications_without_the_summary_or_line_notices():
    rows = line_notices.parse(DUMP)
    assert [(r['talk'], r['sender'], r['text']) for r in rows] == [
        ('グルメ公式', 'グルメ公式', rows[0]['text']),
        ('研究会グループ', '上野花子', '記事を書きました。新しい記事です\nhttps://example.com/a'),
    ]
    assert rows[1]['group'] is True and rows[0]['group'] is False
    assert not any('友だちになりました' in r['text'] for r in rows)   # LINE's own notice
    assert datetime.fromtimestamp(rows[1]['at']).year == 2026


def test_recorder_keeps_each_message_once(tmp_path, monkeypatch):
    monkeypatch.setattr(line_notices, 'ROOT', tmp_path)
    monkeypatch.setattr(line_notices, '_dump', lambda serial=None: DUMP)
    known = set()
    assert line_notices.record_once(known) == 2
    assert line_notices.record_once(known) == 0
    monkeypatch.setattr(line_notices.time, 'time', lambda: 1794528300)
    assert {r['sender'] for r in line_notices.recorded(days=7)} == {'グルメ公式', '上野花子'}


def test_personal_line_keeps_what_was_read_already_from_the_record(tmp_path, monkeypatch):
    monkeypatch.setattr(line_notices, 'ROOT', tmp_path)
    monkeypatch.setattr(line_notices, '_dump', lambda serial=None: DUMP)
    line_notices.record_once(set())
    monkeypatch.setattr(line_notices, '_dump', lambda serial=None: '    NotificationRecord(0x1: pkg=android user=0\n')   # read on the other phone
    monkeypatch.setattr(line_notices.time, 'time', lambda: 1794528300)
    rows = asyncio.run(contact_read.personal())
    assert [r['sender'] for r in rows] == ['上野花子', 'グルメ公式'] and not any(r['unread'] for r in rows)


def test_a_notice_is_told_apart_from_a_person():
    person = {'Return-Path': '<kim@example.jp>'}
    assert contact_read.automated('kim@example.jp', person) is False
    assert contact_read.automated('info@shop.example', {'Return-Path': '<bounces+1-2@em.sendgrid.net>'}) is True   # a sending service
    assert contact_read.automated('order@shop.example', {'Return-Path': '<order@shop.example>', 'Feedback-ID': '1::us-west-2'}) is True
    assert contact_read.automated('no-reply@wlgore.example', person) is True
    assert contact_read.automated('a@b.example', {'List-Unsubscribe': '<mailto:x>'}) is True


def test_the_mail_text_is_its_own_words_without_the_quote_or_the_style():
    raw = ('From: A <a@b.example>\nContent-Type: text/html; charset=utf-8\n\n'
           '<html><head><style>p{color:red}</style></head><body><p>試算表を送ります。</p><p>よろしくお願いします。</p>'
           '<div>2026年11月4日(水) 16:02 本田 &lt;x@y&gt;: 書きました:</div><blockquote>前のメール</blockquote></body></html>')
    text = contact_read.own_text(email.message_from_bytes(raw.encode('utf-8')))
    assert '試算表を送ります。' in text and 'よろしくお願いします。' in text
    assert 'color' not in text and '前のメール' not in text


def test_a_name_matches_every_word_the_model_gave():
    assert contact_read._hits({'from': '金永哲税理士事務所　金永哲', 'address': 'kim@taxdr-kim.example'}, contact_read.words('金さん'))
    rows = [{'sender': '高橋陽一', 'where': '投手コーチイツキの公式LINE'}]
    assert contact_read.found_in(contact_read.words('イツキ 高橋さん'), rows[0]['sender'], rows[0]['where'])
    assert not contact_read.found_in(contact_read.words('イツキ 中村さん'), rows[0]['sender'], rows[0]['where'])


def test_official_line_messages_come_from_the_webhook_records(monkeypatch):
    async def d1(user_id, sql, params=None):
        return [{'channel_key': 'main', 'created_at': '2026-11-07T09:54:12.079Z', 'display_name': '高橋陽一',
                 'payload': json.dumps({'message': {'type': 'text', 'text': '還暦リーグに参戦します'}})},
                {'channel_key': 'fukurou', 'created_at': '2026-11-08T04:32:43.931Z', 'display_name': None,
                 'payload': json.dumps({'message': {'type': 'image', 'id': '1'}})}]
    monkeypatch.setattr(contact_read, '_d1', d1)
    monkeypatch.setattr(contact_read, 'PORNANTI_DB', Path('/nonexistent'))
    rows = asyncio.run(contact_read.official('u'))
    assert [(r['where'], r['sender'], r['text']) for r in rows] == [
        ('ふくろうPの公式LINE', '名前不明', '（写真）'), ('投手コーチイツキの公式LINE', '高橋陽一', '還暦リーグに参戦します')]


def test_the_phone_not_answering_is_said_as_not_read():
    found = {'read_at': '11月13日 12:00', 'personal': [], 'official': [], 'failed': ['個人のLINE（Galaxy の通知）（Galaxy がつながっていない）']}
    assert '届いていないとは言わない' in contact_read.line_digest(found)


def test_the_person_named_in_the_request():
    assert named_person('中村さんからなんか連絡ありましたか') == '中村'
    assert named_person('あの中村さんから何か来た？') == '中村'
    assert named_person('イツキの公式LINEに高橋さんから何か来てた？') == '高橋'
    assert named_person('DisplayModuleさんから返事来た？') == 'DisplayModule'
    assert named_person('税理士の先生から連絡ある？') == '税理士'
    assert named_person('なおっきさんからLINE来た？') == 'なおっき'
    for nobody in ('メッセージ来てるか確認して', 'たくさんメール来てる？', 'お客さんから連絡来てる？'):
        assert named_person(nobody) == ''

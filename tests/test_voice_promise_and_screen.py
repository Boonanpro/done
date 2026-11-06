"""The 2026-11-05 15:05 call (the owner's 「直して」 of 11/6).

- 「R630の公式ページへのリンクを入れて、先生宛てのメールを作り直すね。ちょっと待ってて」 and no request ran: the owner asked twice
  whether the mail was done and got 「まだ」 for 7 min. A promise with no delegation is now routed by the server itself.
- The revision asked the owner which product and for its address, though both were found in the call; the address was read
  out; a second run drafted a message nobody asked for. The earlier backend now gets the call's drafts and findings.
- The screen: a product's page showed its top only, a difference showed one page, a place no map."""
import asyncio
import io
import json
import time

import pytest

from app.services import voice_router, voice_stage
from app.services.voice_sideband import Dialogue


@pytest.fixture(autouse=True)
def router_on(monkeypatch):
    monkeypatch.setenv('DAN_VOICE_ROUTER', '1')
    monkeypatch.setenv('DAN_VOICE_PLAIN', '1')
    monkeypatch.setattr('app.services.command_job_state.list_owned', lambda user, room: [])


MAIL_CALL = [('user', 'まろっぴゃくさんじゅうを買おうと思っているので、商品リンクもちゃんとつけてメールを作ってください、まだ送るなよ'),
             ('assistant', 'うん、わかった。少し確認したいんだけど、「まろっぴゃくさんじゅう」って、どの商品か聞き取れなかったんだよね。商品名かリンクを送ってくれる?'),
             ('user', 'あるろっぴゃくさんじゅうやん、最初に言ったやろ'),
             ('assistant', 'あ、そうだったね、うん。R630の公式ページへのリンクを入れて、先生宛てのメールを作り直すね。ちょっと待ってて。今回はまだ送信しないよ。')]


def make(turns, quiet=3.0, delegated_after=False):
    sent, log = [], []
    async def send(event): sent.append(event)
    dialogue = Dialogue()
    for role, text in turns:
        dialogue.add(role, text)
    now = time.monotonic()
    dialogue.heard_at = now - quiet - 1
    dialogue.delegated_at = (now - quiet - .5) if delegated_after else (now - 60)
    r = voice_router.Router('s', 'u', 'r', dialogue, send, lambda phase, **f: log.append((phase, f)), {'dan_words': now - quiet}, backend={'model': 'm'})
    return r, sent, log


@pytest.mark.asyncio
async def test_a_promise_that_no_request_carried_is_routed_by_the_server():
    r, sent, log = make(MAIL_CALL)
    try:
        assert r.unrouted_promise() == 3
        routed = []
        async def route(): return 'message', '', '', .95, 150
        async def luna(delegation_id, created): routed.append((delegation_id, r.last_words))
        r.route, r.luna = route, luna
        r.start_promised('promise')
        await asyncio.sleep(.6)
        assert routed and routed[0][0].startswith('auto-')
        assert 'まろっぴゃくさんじゅう' in routed[0][1] and 'あるろっぴゃくさんじゅう' in routed[0][1]   # both of the owner's turns
        assert ('promise_unrouted', {'why': 'promise'}) in log
        assert r.unrouted_promise() is None   # read once
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_no_promise_when_dan_asks_answers_himself_or_a_request_went_out():
    asked = MAIL_CALL[:2]
    answered = [('user', '筋トレ器具って経費にできるかな'),
                ('assistant', 'ちょっとその扱いを確認するね。えっとね、筋トレ器具一式は、仕事場に置いても経費として認められない可能性が高いと思う。税理士さんに事前に相談して、経費として通るか確かめてから買うのが安全だと思うよ。')]
    for turns, kw in ((asked, {}), (answered, {}), (MAIL_CALL, {'delegated_after': True}), (MAIL_CALL, {'quiet': .5})):
        r, _, _ = make(turns, **kw)
        try: assert r.unrouted_promise() is None, (turns[-1][1][:20], kw)
        finally: await r.close()


@pytest.mark.asyncio
async def test_a_short_answer_to_dans_question_carries_the_request_it_answers():
    r, _, _ = make([('user', 'パワーラックとハーフラックって何が違う'), ('assistant', 'パワーラックとハーフラックの違いについて聞きたい、で合ってる?'), ('user', '合ってる')])
    try:
        r.last_words = 'パワーラックとハーフラックって何が違う'
        r.mark = (1, 0)
        words = r.request_words()
        assert 'パワーラックとハーフラック' in words and '合ってる' in words
        r.last_words = ''
        assert r.request_words() == '合ってる'   # no earlier request: the words alone
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_a_promised_run_speaks_without_a_delegation_and_reads_no_address():
    r, sent, _ = make(MAIL_CALL)
    try:
        await r.reply('auto-1', time.monotonic(), 'レボルワンのR630の公式ページは https://revoluone.com/r630/ にある。', spoken=True)
        spoken = [e for e in sent if e['type'] == 'session.commentary.append']
        silent = [e for e in sent if e['type'] == 'session.thinking.append']
        assert spoken and all(e['delegation_id'] is None for e in sent)
        assert all('https://' not in e['content'] for e in spoken)
        assert any('https://revoluone.com/r630/' in e['content'] for e in silent)   # the speech model still knows it
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_the_earlier_backend_gets_the_calls_draft_findings_and_running_work(monkeypatch):
    from app.services import voice_lookup
    r, _, _ = make(MAIL_CALL)
    try:
        class Stage: scenes = [{'card': {'proposal_id': 'p1', 'to_name': '金先生', 'subject': '筋トレ器具の経費計上', 'body': '金先生 お世話になっております。'}},
                               {'caption': 'R630', 'page_url': 'https://revoluone.com/r630/'}]
        r.stage = Stage()
        class L: label, answer, state = 'R630', 'レボルワンのR630は5つの機能のオールインワンラックで税込451,000円。', 'answered'
        monkeypatch.setattr(voice_lookup, 'for_call', lambda u, room: type('C', (), {'lookups': {'a': L()}})())
        text = r.call_context(['筋トレ器具のメール'])
        assert 'proposal_id p1' in text and 'revise_message_on_stage' in text
        assert 'https://revoluone.com/r630/' in text and '451,000円' in text
        assert '筋トレ器具のメール' in text
        assert '頼まれていない相手への下書き' in voice_router.LUNA_RULES
    finally:
        await r.close()


class Host:
    def __init__(self, shot=None, scroll='価格'):
        self.asked, self.shot, self.scroll = [], shot, scroll
    async def ask(self, op, with_media=False, **fields):
        self.asked.append(fields)
        args = fields.get('arguments') or {}
        if args.get('action') == 'evaluate': return f'evaluate result: {self.scroll}'
        if args.get('action') == 'read': return '本文 R630 価格 451,000円'
        if with_media: return {'stage_image': self.shot, 'stage_stream': self.shot}
        return 'ok'


def stage_with(monkeypatch, tmp_path, host):
    from app.services import voice_tools, voice_screen_media
    monkeypatch.setattr(voice_tools, 'host', lambda u, r: host)
    monkeypatch.setattr(voice_stage, 'ROOT', tmp_path)
    monkeypatch.setattr(voice_screen_media, 'ROOT', tmp_path)
    monkeypatch.setattr(voice_stage, 'SETTLE_SHOT_S', 0)
    s = voice_stage.Stage('room1', 'sess', Dialogue(), lambda *a, **k: None, user_id='u')
    return s


def picture(tmp_path, name, colour):
    from PIL import Image
    from app.services import voice_screen_media
    folder = voice_screen_media.directory('room1'); folder.mkdir(parents=True, exist_ok=True)
    hexname = (name * 32)[:32]
    image = Image.new('RGB', (1280, 800), colour)
    for x in range(0, 1280, 40): image.paste((250, 250, 250), (x, 700, x + 20, 800))   # not one flat colour (voice_screen_media.blank)
    image.save(folder / (hexname + '.png'))
    return '/api/v1/voicelog/stage/' + voice_screen_media._name('room1') + '/image/' + hexname + '.png'


@pytest.mark.asyncio
async def test_a_place_goes_on_the_screen_as_a_map_at_once(monkeypatch, tmp_path):
    host = Host()
    s = stage_with(monkeypatch, tmp_path, host)
    host.shot = picture(tmp_path, 'a', (30, 120, 200))
    out = await s.show_search('map', 'レボルワン 大阪ショールーム 大阪市阿倍野区西田辺町2-6-21')
    assert out['shown']
    opened = host.asked[0]['arguments']['url']
    assert opened.startswith('https://www.google.com/maps/search/?api=1&query=') and '%E3%83%AC' in opened
    assert s.caption.startswith('地図:') and s.scenes[-1]['page_url'] == opened
    out = await s.show_search('images', 'レボルワン R630')
    assert 'tbm=isch' in [a for a in host.asked if (a.get('arguments') or {}).get('action') == 'open_target'][-1]['arguments']['url'] and s.caption.startswith('画像:')


@pytest.mark.asyncio
async def test_a_difference_shows_both_pages_at_the_part_asked_about(monkeypatch, tmp_path):
    from PIL import Image
    from app.services import voice_screen_media
    host = Host()
    s = stage_with(monkeypatch, tmp_path, host)
    shots = iter([picture(tmp_path, 'b', (200, 40, 40)), picture(tmp_path, 'c', (40, 200, 40))])
    real_ask = host.ask
    async def ask(op, with_media=False, **fields):
        if with_media: return {'stage_image': next(shots)}
        return await real_ask(op, with_media, **fields)
    host.ask = ask
    out = await s.compare_pages(['https://revoluone.com/r630/', 'https://revoluone.com/r490/'], ['R630', 'R490'], '仕様 価格')
    assert out['shown'] and [p['name'] for p in out['pages']] == ['R630', 'R490'] and '451,000円' in out['pages'][0]['text']
    assert sum(1 for a in host.asked if (a.get('arguments') or {}).get('action') == 'evaluate') == 2   # each scrolled to the part
    path = voice_screen_media.local_file(s.image)
    with Image.open(path) as shown:
        assert shown.width == 960 and shown.height > 1200   # stacked: readable on the phone
        assert shown.getpixel((480, 300))[0] > 150 and shown.getpixel((480, 300 + 60 + 600 + 12))[1] > 150   # R630 above, R490 below
    assert s.caption == 'R630 と R490'
    assert (await s.compare_pages(['https://a.example/'], [], ''))['shown'] is False


@pytest.mark.asyncio
async def test_a_shown_page_is_scrolled_to_the_focus_and_its_text_comes_back(monkeypatch, tmp_path):
    from app.services import voice_page_check
    host = Host()
    s = stage_with(monkeypatch, tmp_path, host)
    host.shot = picture(tmp_path, 'd', (90, 90, 160))
    async def check(text, conditions): return None
    monkeypatch.setattr(voice_page_check, 'check', check)
    out = await s.show_page('https://revoluone.com/r630/', note='R630', focus='価格 仕様')
    assert out['shown'] and '451,000円' in out['page_text']
    evaluated = next(a for a in host.asked if (a.get('arguments') or {}).get('action') == 'evaluate')['arguments']['expression']
    assert '["価格", "仕様"]' in evaluated
    assert s.scenes[-1]['page_url'] == 'https://revoluone.com/r630/'


def test_the_lookup_is_told_to_show_pictures_maps_and_comparisons():
    from app.services import voice_lookup
    names = [t['name'] for t in voice_lookup.tools()]
    assert 'show_search_on_stage' in names and 'compare_pages_on_stage' in names
    text = voice_lookup.instructions()
    assert 'show_search_on_stage' in text and 'compare_pages_on_stage' in text and 'focus' in text
    assert '別の機種' in text and 'share_progress だけの手は作らない' in text

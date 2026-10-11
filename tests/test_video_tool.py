"""Dan looks at a video when the work needs it (2026-10-11). Before, a message with a YouTube URL was analysed before Dan
started; the wait outlasted the relay's patience and the message was never answered (2026-10-09, twice)."""
import asyncio
import json
import sys
import types

import pytest

from app.services import video_analyzer


def captions_source(monkeypatch, info, events):
    class FakeYDL:
        def __init__(self, options): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def extract_info(self, url, download): return info
        def urlopen(self, url): return types.SimpleNamespace(read=lambda: json.dumps({'events': events}).encode())
    monkeypatch.setitem(sys.modules, 'yt_dlp', types.SimpleNamespace(YoutubeDL=FakeYDL))


def test_captions_come_as_text_with_a_time_mark_about_every_30_seconds(monkeypatch):
    info = {'title': '題', 'duration': 95, 'language': 'ja', 'subtitles': {},
            'automatic_captions': {'en': [{'ext': 'json3', 'url': 'translated'}], 'ja': [{'ext': 'vtt', 'url': 'v'}, {'ext': 'json3', 'url': 'j'}]}}
    events = [{'tStartMs': 0, 'segs': [{'utf8': 'こんにちは'}]}, {'tStartMs': 2000, 'segs': [{'utf8': '\n'}]},
              {'tStartMs': 12000, 'segs': [{'utf8': '今日は'}, {'utf8': '台本の話'}]}, {'tStartMs': 61000, 'segs': [{'utf8': '次に'}]}]
    captions_source(monkeypatch, info, events)
    text = video_analyzer._youtube_captions_sync('https://youtu.be/x')
    assert text.splitlines() == ['題（1分35秒）', '自動生成の字幕（聞き取り間違いを含む）', '', '[0:00] こんにちは今日は台本の話', '[1:01] 次に']


def test_the_uploaders_captions_win_over_the_automatic_ones_and_none_is_none(monkeypatch):
    info = {'title': 't', 'duration': 5, 'language': 'ja', 'subtitles': {'ja': [{'ext': 'json3', 'url': 'm'}]},
            'automatic_captions': {'ja': [{'ext': 'json3', 'url': 'a'}]}}
    captions_source(monkeypatch, info, [{'tStartMs': 0, 'segs': [{'utf8': '本文'}]}])
    assert '投稿者が付けた字幕' in video_analyzer._youtube_captions_sync('https://youtu.be/x')
    captions_source(monkeypatch, {'title': 't', 'subtitles': {}, 'automatic_captions': {}}, [])
    assert video_analyzer._youtube_captions_sync('https://youtu.be/x') is None


@pytest.mark.asyncio
async def test_captions_reads_what_youtube_holds_and_never_calls_gemini(monkeypatch):
    monkeypatch.setattr(video_analyzer, '_youtube_captions_sync', lambda url: '字幕 ' + url)
    monkeypatch.setattr(video_analyzer, '_analyze_youtube_sync', lambda *a: pytest.fail('Gemini was called'))
    out = await video_analyzer.tool({'action': 'captions', 'source': 'https://www.youtube.com/watch?v=abc', 'question': '書き添えても字幕は字幕'})
    assert out == {'success': True, 'output': '字幕 https://www.youtube.com/watch?v=abc'}
    assert (await video_analyzer.tool({'action': 'captions', 'source': 'D:/a.mp4'}))['success'] is False   # YouTube alone holds captions


@pytest.mark.asyncio
async def test_the_way_is_named_not_guessed_from_what_was_left_out(monkeypatch):
    monkeypatch.setattr(video_analyzer, '_youtube_captions_sync', lambda url: pytest.fail('captions were fetched'))
    monkeypatch.setattr(video_analyzer, '_analyze_youtube_sync', lambda *a: pytest.fail('Gemini was called'))
    assert 'captions か ask' in (await video_analyzer.tool({'source': 'https://youtu.be/abc'}))['error']
    assert 'question' in (await video_analyzer.tool({'action': 'ask', 'source': 'https://youtu.be/abc'}))['error']
    assert video_analyzer.TOOL['input_schema']['required'] == ['action', 'source']


@pytest.mark.asyncio
async def test_ask_has_gemini_answer_that_question_about_a_url_or_an_attachment(monkeypatch, tmp_path):
    asked = []
    monkeypatch.setattr(video_analyzer.settings, 'GOOGLE_GEMINI_API_KEY', 'k')
    monkeypatch.setattr(video_analyzer, '_analyze_youtube_sync', lambda url, q: asked.append((url, q)) or '答え')
    monkeypatch.setattr(video_analyzer, '_analyze_file_sync', lambda path, q: asked.append((path, q)) or 'ファイルの答え')
    assert (await video_analyzer.tool({'action': 'ask', 'source': 'https://youtu.be/abc', 'question': '冒頭30秒の構成は'}))['output'] == '答え'
    (tmp_path / 'clip.mp4').write_bytes(b'x')
    monkeypatch.setattr(video_analyzer, 'UPLOADS_DIR', str(tmp_path))
    assert (await video_analyzer.tool({'action': 'ask', 'source': '/api/v1/files/clip.mp4', 'question': '何が映っている'}))['output'] == 'ファイルの答え'
    assert [(where, q.split('\n')[0]) for where, q in asked] == [('https://youtu.be/abc', '冒頭30秒の構成は'), (str(tmp_path / 'clip.mp4'), '何が映っている')]
    missing = await video_analyzer.tool({'action': 'ask', 'source': '/api/v1/files/none.mp4', 'question': 'q'})
    assert missing['success'] is False and '見つからない' in missing['error']


@pytest.mark.asyncio
async def test_dan_gets_the_answer_without_geminis_working_notes(monkeypatch):
    """2026-10-11, the same question three times: an empty answer, notes with the answer run on after them, and (with
    marks to aim for) the answer alone."""
    monkeypatch.setattr(video_analyzer.settings, 'GOOGLE_GEMINI_API_KEY', 'k')
    replies = iter(['thought\n0:30を確認。<answer>下書き</answer>\nもう一度見る。thought\n完璧です。<answer>\n女性との会話のゴールって\n</answer>'])
    monkeypatch.setattr(video_analyzer, '_analyze_youtube_sync', lambda url, q: next(replies))
    out = await video_analyzer.tool({'action': 'ask', 'source': 'https://youtu.be/abc', 'question': 'q'})
    assert out == {'success': True, 'output': '女性との会話のゴールって'}
    assert video_analyzer._final_answer('印なしで全部書いた') == '印なしで全部書いた'
    assert video_analyzer._final_answer('メモ <answer>途中で切れ') == '途中で切れ'
    # the shape of the third real call: the mark opened, more notes, opened again, never closed
    assert video_analyzer._final_answer('確認する。<answer>\nタグ内に出力しよう。<answer>\n女性との会話のゴールって\n\n（※補足）') == '女性との会話のゴールって\n\n（※補足）'


@pytest.mark.asyncio
async def test_an_empty_answer_is_asked_once_more_and_then_reported(monkeypatch):
    monkeypatch.setattr(video_analyzer.settings, 'GOOGLE_GEMINI_API_KEY', 'k')
    replies = [None, '<answer>二度目で答えた</answer>']
    monkeypatch.setattr(video_analyzer, '_analyze_youtube_sync', lambda url, q: replies.pop(0))
    assert (await video_analyzer.tool({'action': 'ask', 'source': 'https://youtu.be/abc', 'question': 'q'}))['output'] == '二度目で答えた'
    calls = []
    monkeypatch.setattr(video_analyzer, '_analyze_youtube_sync', lambda url, q: calls.append(q))
    out = await video_analyzer.tool({'action': 'ask', 'source': 'https://youtu.be/abc', 'question': 'q'})
    assert out['success'] is False and '2回とも' in out['error'] and len(calls) == 2


@pytest.mark.asyncio
async def test_a_gemini_failure_reaches_dan_in_words(monkeypatch):
    def fail(url, q): raise RuntimeError('quota exceeded')
    monkeypatch.setattr(video_analyzer.settings, 'GOOGLE_GEMINI_API_KEY', 'k')
    monkeypatch.setattr(video_analyzer, '_analyze_youtube_sync', fail)
    out = await video_analyzer.tool({'action': 'ask', 'source': 'https://youtu.be/abc', 'question': 'q'})
    assert out['success'] is False and 'quota exceeded' in out['error']


def test_dan_has_the_tool():
    from app.agent.v2 import tools
    assert 'video' in [t['name'] for t in tools.get_all_skill_tools()]
    assert tools.parse_tool_name('video') == ('_video', 'read')


@pytest.mark.asyncio
async def test_nothing_about_media_stands_between_a_saved_message_and_dan_starting(monkeypatch):
    from app.api import chat_routes
    assert not hasattr(chat_routes, '_enrich_content_with_video_analysis')   # no analysis before Dan starts
    finished = asyncio.Event()

    async def slow(**kwargs):
        await asyncio.sleep(0.05)
        finished.set()
    monkeypatch.setattr(chat_routes, '_save_media_artifacts', slow)
    chat_routes._save_media_artifacts_in_background(image_urls=[], file_urls=[], message_content='', room_id='r')
    assert not finished.is_set()   # the caller goes on to start Dan
    await asyncio.wait_for(finished.wait(), 1)   # and the description is still written

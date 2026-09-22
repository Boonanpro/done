import json
import pytest
from app.services import editor_references as refs, timeline_draft as td


@pytest.fixture
def room(tmp_path, monkeypatch):
    monkeypatch.setattr(td, 'UPLOAD_ROOT', tmp_path)
    root = tmp_path / 'room'
    root.mkdir()
    (root / 'contents.json').write_text(json.dumps([{'id':'a','timeline':{'tracks':[]}}, {'id':'b'}]))
    return root


def test_x_resolves_actual_video_and_reuses_across_query_strings(room, monkeypatch):
    calls = []
    class Response:
        def json(self):
            return {'text':'Author claim', 'video':{'durationMs':30000,'variants':[
                {'src':'https://video.twimg.com/demo/1280x720/movie.mp4'}]}}
    def get(url, **kwargs):
        calls.append(url)
        return Response()
    monkeypatch.setattr(refs, '_get', get)
    one = refs.resolve('room','a','https://x.com/author/status/123?s=20')
    two = refs.resolve('room','b','https://x.com/author/status/123?s=99')
    assert one['item']['url'].endswith('movie.mp4')
    assert two['cached'] and one['reference']['id'] == two['reference']['id']
    assert len(calls) == 2
    assert refs.read('room','b')['references'][0]['post_text'] == 'Author claim'
    assert td._read_contents_raw('room')[0]['timeline'] == {'tracks':[]}


def test_reference_access_is_scoped_to_content(room):
    (room/'assets.json').write_text(json.dumps([{'id':'asset','kind':'video','filename':'mine.mp4'}]))
    ref = refs.resolve('room','a','asset')['reference']
    with pytest.raises(ValueError):
        refs.read('room','b',ref['id'])
    assert refs.read('room','a')['references'][0]['item']['asset_id'] == 'asset'
    with pytest.raises(ValueError):
        refs.resolve('room','a','missing-asset')


def test_private_network_reference_is_rejected(monkeypatch):
    monkeypatch.setattr(refs.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError):
        refs._public_url('https://internal.example/secret.mp4')

def test_vimeo_reference_keeps_playable_video_instead_of_page_thumbnail(room,monkeypatch):
    monkeypatch.setattr(refs,'_public_url',lambda url:url)
    monkeypatch.setattr(refs,'_get',lambda *a,**k:pytest.fail('Vimeo embed needs no page thumbnail'))
    item=refs.resolve('room','a','https://vimeo.com/1039245474')['item']
    assert item['kind']=='video' and item['url']=='https://vimeo.com/1039245474'

def test_vimeo_page_is_not_uploaded_as_an_mp4(room,monkeypatch):
    monkeypatch.setattr(refs,'_public_url',lambda url:url)
    ref=refs.resolve('room','a','https://vimeo.com/1039245474')['reference']
    monkeypatch.setattr(refs.httpx,'stream',lambda *a,**k:pytest.fail('must reject before download/upload'))
    with pytest.raises(ValueError,match='動画ファイルではありません'):
        refs.analyze('room','a',ref['id'],'inspect')

def test_concurrent_same_analysis_shares_success_cache(room,monkeypatch):
    import concurrent.futures,threading,time
    monkeypatch.setattr(refs,'_public_url',lambda url:url)
    ref=refs.resolve('room','a','https://www.youtube.com/watch?v=abcdefghijk')['reference']
    calls=[]
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'steps':[{'type':'model_output','content':[{'text':'Observed scene'}]}]}
    def post(*a,**k):calls.append(1);time.sleep(.08);return Response()
    monkeypatch.setattr(refs.httpx,'post',post)
    barrier=threading.Barrier(2)
    def run():barrier.wait();return refs.analyze('room','a',ref['id'],'same')
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda _:run(),range(2)))
    assert len(calls)==1 and sum(bool(r.get('cached')) for r in results)==1
    assert not refs._analysis_locks


def test_saved_analysis_is_available_to_later_production(room):
    (room/'assets.json').write_text(json.dumps([{'id':'asset','kind':'video'}]))
    ref = refs.resolve('room','a','asset')['reference']
    refs._save(refs._folder('room')/(ref['id']+'-question.analysis.json'), {'analysis':'observations'})
    result = refs.read('room','a',ref['id'])['references'][0]
    assert result['inspection'] == 'analyzed'
    assert result['analyses'][0]['analysis'] == 'observations'

def test_analysis_failure_keeps_reason_without_credentials_or_success_cache(room, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(refs,'_public_url',lambda url:url)
    monkeypatch.setattr(settings,'GOOGLE_GEMINI_API_KEY','test-secret-key')
    ref=refs.resolve('room','a','https://www.youtube.com/watch?v=abcdefghijk')['reference']
    response=refs.httpx.Response(400,json={'error':{'message':'Unable to fetch https://example.com/?key=test-secret-key; test-secret-key'}},request=refs.httpx.Request('POST','https://example.com'))
    monkeypatch.setattr(refs.httpx,'post',lambda *a,**k:response)
    with pytest.raises(ValueError,match='HTTP 400'):
        refs.analyze('room','a',ref['id'],'observe')
    failures=list(refs._folder('room').glob('*.error.json'))
    assert len(failures)==1
    saved=failures[0].read_text(encoding='utf8')
    assert 'test-secret-key' not in saved and 'Unable to fetch' in saved
    assert refs.read('room','a')['references'][0]['inspection']=='not_analyzed'


def test_followup_question_reuses_upload_and_identical_question_reuses_analysis(room, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from google import genai
    local=room/'test.mp4';local.write_bytes(b'test video')
    (room/'assets.json').write_text(json.dumps([{'id':'asset','kind':'video','local_path':str(local)}]))
    ref=refs.resolve('room','a','asset')['reference']
    uploads=[];analyses=[]
    def upload(**kwargs):
        uploads.append(kwargs)
        return SimpleNamespace(state=SimpleNamespace(name='ACTIVE'),uri='https://example.test/file',expiration_time=datetime.now(timezone.utc)+timedelta(hours=1))
    monkeypatch.setattr(genai,'Client',lambda **k:SimpleNamespace(files=SimpleNamespace(upload=upload)))
    class Response:
        def raise_for_status(self):pass
        def json(self):
            return {'steps':[{'type':'processing_call'},{'type':'model_output','content':[{'text':'Observed scene'}]}]}
    def post(*a,**k):analyses.append(k['json']);return Response()
    monkeypatch.setattr(refs.httpx,'post',post)
    assert refs.analyze('room','a',ref['id'],'first')['agentic_observed']
    refs.analyze('room','a',ref['id'],'different question')
    assert refs.analyze('room','a',ref['id'],'first')['cached']
    assert len(uploads)==1 and len(analyses)==2

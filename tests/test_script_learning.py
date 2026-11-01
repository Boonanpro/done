import asyncio
import io
import json
import time
import zipfile
from unittest.mock import AsyncMock

import pytest
from app.services import script_learning as L, gdoc_events as E


def docx(body, comments=''):
    buf=io.BytesIO()
    ns='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    with zipfile.ZipFile(buf,'w') as z:
        z.writestr('word/document.xml',f'<w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>')
        if comments:z.writestr('word/comments.xml',f'<w:comments xmlns:w="{ns}">{comments}</w:comments>')
    return buf.getvalue()


def text(s):return f'<w:r><w:t>{s}</w:t></w:r>'
def paragraph(s):return '<w:p>'+text(s)+'</w:p>'
def insertion(s,ident='1',author='Owner'):
    return f'<w:ins w:id="{ident}" w:author="{author}">{text(s)}</w:ins>'


@pytest.fixture
def target(tmp_path,monkeypatch):
    monkeypatch.setattr(E,'ROOT',tmp_path)
    with E.db() as c:
        c.execute('INSERT INTO docs(file_id,room_id,user_id,project_id,account,dirty) VALUES(?,?,?,?,?,?)',('f','r','u','p','test',1))
    with L.db() as c:c.execute('INSERT INTO targets(file_id) VALUES(?)',('f',))
    return {'file_id':'f','room_id':'r','user_id':'u','project_id':'p','account':'test','dirty':1}


def test_unaccepted_suggestion_can_be_edited_without_accepting(target):
    a=docx('<w:p>'+text('導入。')+insertion('海外で増えています。')+text('次は買う話です。')+'</w:p>')
    b=docx('<w:p>'+text('導入。')+insertion('AIで一人でも始めやすくなりました。')+text('次は買う話です。')+'</w:p>')
    first=L.store('f',a,{});second=L.store('f',b,{})
    with L.db() as c:change=dict(c.execute('SELECT * FROM changes').fetchone())
    delta=json.loads(change['payload'])
    assert delta['before']==[] and delta['after'][0]['new']==['導入。AIで一人でも始めやすくなりました。次は買う話です。']
    assert delta['suggestions_changed']
    assert first['snapshot']!=second['snapshot']
    assert len(list((E.ROOT/'snapshots'/'f').glob('*.docx')))==2


def test_direct_edit_and_suggestion_on_top_of_suggestion(target):
    a=docx('<w:p>'+insertion('話を飛ばす。',author='Dan')+'</w:p>')
    b=docx('<w:p>'+insertion('前の話を受ける。',author='Dan')+insertion('次へつなぐ。','2')+'</w:p>')
    L.store('f',a,{})
    L.store('f',b,{})
    c=docx(paragraph('話のつながりを具体的に書く。'))
    L.store('f',c,{})
    with L.db() as db:
        rows=db.execute('SELECT payload FROM changes').fetchall()
        assert len(rows)==2
        assert json.loads(rows[0][0])['after']
        assert json.loads(rows[1][0])['before']
        assert 'unknown' in json.loads(rows[1][0])['attribution']


def test_comments_alone_and_resolution_preserved(target):
    a=docx(paragraph('本文'))
    L.store('f',a,{},[])
    t={'id':'c','content':'この前の話とのつながりがない','author':{'displayName':'Owner'}}
    L.store('f',a,{},[t])
    L.store('f',a,{},[{**t,'resolved':True}])
    with L.db() as c:
        changes=[json.loads(r[0]) for r in c.execute('SELECT payload FROM changes')]
    assert len(changes)==2 and all(r['comments_changed'] for r in changes)
    assert all(not r['before'] and not r['after'] for r in changes)


def test_export_ids_and_modified_times_do_not_generate_duplicate_learning(target):
    a=docx('<w:p>'+insertion('提案','1')+'</w:p>')
    b=docx('<w:p>'+insertion('提案','98')+'</w:p>')
    t={'id':'c','content':'コメント','modifiedTime':'old'}
    L.store('f',a,{},[t]);r=L.store('f',b,{'version':'new'},[{**t,'modifiedTime':'new'}])
    assert not r['changed']
    with L.db() as c:assert not c.execute('SELECT * FROM changes').fetchall()


def test_deletion_tabs_and_table_context():
    a=docx('<w:tbl><w:tr><w:tc><w:p>'+text('前')+'<w:del w:id="1" w:author="Owner"><w:r><w:delText>長い言葉</w:delText></w:r></w:del>'+insertion('短く')+'</w:p></w:tc></w:tr></w:tbl>')
    p=L.parse_docx(a)
    assert p['paragraphs'][0]['before']=='前長い言葉'
    assert p['paragraphs'][0]['after']=='前短く'
    assert {r['kind'] for r in p['revisions']}=={'ins','del'}


def test_capture_requires_consistent_version_and_keeps_raw(target,monkeypatch):
    from app.services import gdoc_drive as G
    versions=iter([{'version':'1'},{'version':'2'}])
    monkeypatch.setattr(G,'request',lambda *a,**kw:next(versions))
    monkeypatch.setattr(G,'export_docx',lambda *a:docx(paragraph('保存中')))
    monkeypatch.setattr(G,'comments',lambda *a:[])
    with pytest.raises(ValueError,match='changed'):L.capture(target)
    with L.db() as c:assert c.execute('SELECT count(*) FROM snapshots').fetchone()[0]==0


def test_missed_push_reconciles_and_failures_are_bounded(target,monkeypatch):
    called=[]
    monkeypatch.setattr(L,'capture',lambda *a,**kw:called.append(kw))
    L.collect_due(target);L.collect_due(target)
    assert len(called)==1
    with L.db() as c:c.execute('UPDATE targets SET due=0')
    L.collect_due(target)
    assert len(called)==2
    def fail(*a,**kw):raise RuntimeError('offline')
    monkeypatch.setattr(L,'capture',fail)
    for _ in range(4):
        with L.db() as c:c.execute('UPDATE targets SET due=0')
        L.collect_due(target)
    with L.db() as c:
        t=c.execute('SELECT * FROM targets').fetchone()
        assert t['failures']==3 and t['error']=='RuntimeError'


def test_dan_edit_boundaries_and_serial_learning(target,monkeypatch):
    L.store('f',docx(paragraph('元の文章')), {})
    captures=iter([docx(paragraph('本人が修正')),docx(paragraph('ダンが修正'))])
    monkeypatch.setattr(L,'capture',lambda doc,origin='observed':L.store('f',next(captures),{},origin=origin))
    L.edit_boundary(target,'before')
    assert L.prepare_job('f',time.time()+1000) is None
    L.edit_boundary(target,'after')
    jid=L.prepare_job('f',time.time()+1000)
    assert jid and L.prepare_job('f',time.time()+1000) is None
    bundle=L.evidence(jid)
    assert bundle['changes'][0]['payload']['origin']=='observed'
    assert bundle['changes'][1]['payload']['origin']=='dan-or-concurrent'


def test_complete_requires_all_changes_and_quality_evidence(target):
    L.store('f',docx(paragraph('古い')),{});L.store('f',docx(paragraph('直した')), {})
    jid=L.prepare_job('f',time.time()+1000)
    ids=[c['id'] for c in L.evidence(jid)['changes']]
    with pytest.raises(ValueError):L.complete(jid,{'outcome':'no_lesson','change_ids':[],'reason':'なし'})
    with pytest.raises(ValueError):L.complete(jid,{'outcome':'promoted','change_ids':ids,'reason':'改善'})
    L.complete(jid,{'outcome':'deferred','change_ids':ids,'reason':'作者が不明。次の本人の添削と照合する。',
                    'lessons':[{'rule':'手順候補','scope':'途中の追記','exceptions':'数値訂正','basis':'inferred','evidence_ids':ids}]})
    assert 'deferred' in L.context('r')
    assert L.context('another-room')==''


@pytest.mark.asyncio
async def test_private_runner_requires_report_and_restart_does_not_replay(target,monkeypatch):
    from app.services import command_job_state as S, job_process as J, parallel_job_runner as P
    monkeypatch.setattr(S,'ROOT',E.ROOT/'jobs');monkeypatch.setattr(P,'room_model',lambda _: 'astra')
    L.store('f',docx(paragraph('前')),{});L.store('f',docx(paragraph('後')), {})
    jid=L.prepare_job('f',time.time()+1000); calls=[]
    async def launch(row):
        calls.append(row)
        s=S.read(jid)
        assert s['quiet'] and s['origin_room_id']=='r'
        assert 'skill-creator' in s['task'] and '共通ルール' in s['task']
        S.change(jid,lambda s:s.update(state='completed',result='できました'))
    monkeypatch.setattr(J,'launch',launch)
    await L.run_job(target,jid)
    with L.db() as c:assert c.execute('SELECT status FROM jobs').fetchone()[0]=='needs_attention'
    assert not L.prepare_job('f',time.time()+2000)
    # Existing terminal processes must not be relauched through the worker.
    tasks={};monkeypatch.setattr(L,'collect_due',lambda d:time.time()+300)
    await L.tick([target],tasks)
    assert len(calls)==1 and not tasks


def test_learning_context_is_in_assembled_room_context(target):
    L.store('f',docx(paragraph('本文')), {})
    assert '保存版数=1' in E.room_context('r')

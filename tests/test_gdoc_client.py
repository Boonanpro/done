import io
import zipfile

from app.services import gdoc_client as C

NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def docx(body, comments=False):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Override PartName="/word/comments.xml" ContentType="x"/></Types>')
        z.writestr('word/_rels/document.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="r9" Type="t" Target="comments.xml"/></Relationships>')
        z.writestr('word/document.xml', f'<w:document xmlns:w="{NS}"><w:body>{body}</w:body></w:document>')
        if comments: z.writestr('word/comments.xml', f'<w:comments xmlns:w="{NS}"><w:comment w:id="0"><w:p><w:r><w:t>命令口調のメモ</w:t></w:r></w:p></w:comment></w:comments>')
    return buf.getvalue()


def r(t, bold=False): return f'<w:r>{"<w:rPr><w:b/></w:rPr>" if bold else ""}<w:t xml:space="preserve">{t}</w:t></w:r>'
def p(*runs, mark=''): return f'<w:p>{mark}{"".join(runs)}</w:p>'
def ins(t): return f'<w:ins w:id="1" w:author="本人">{r(t)}</w:ins>'
def dele(t): return f'<w:del w:id="2" w:author="ダン"><w:r><w:delText>{t}</w:delText></w:r></w:del>'


def test_clean_keeps_confirmed_text_only_and_drops_comments():
    raw = docx(p(r('見出し', True)) + p('<w:commentRangeStart w:id="0"/>', r('最初の'), dele('文です。'), ins('文章。'),
               '<w:commentRangeEnd w:id="0"/><w:r><w:commentReference w:id="0"/></w:r>')
               + p(ins('足した段落'), mark='<w:pPr><w:rPr><w:ins w:id="3" w:author="本人"/></w:rPr></w:pPr>'), comments=True)
    out = C.clean(raw)
    z = zipfile.ZipFile(io.BytesIO(out))
    assert 'word/comments.xml' not in z.namelist() and b'comments.xml' not in z.read('word/_rels/document.xml.rels')
    assert C.pending_suggestions(out) == 0 and b'commentRange' not in z.read('word/document.xml')
    assert C.texts(out) == ['見出し', '最初の文です。']
    assert C.texts(raw, 'before') == ['見出し', '最初の文です。'] and C.texts(raw, 'after') == ['見出し', '最初の文章。', '足した段落']



def test_accept_applies_every_suggestion_and_joins_deleted_paragraph_breaks():
    gone = '<w:pPr><w:rPr><w:del w:id="4" w:author="ダン"/></w:rPr></w:pPr>'
    raw = docx(p(r('見出し', True)) + p(r('最初の'), dele('文です。'), ins('文章。'))
               + p(ins('足した段落'), mark='<w:pPr><w:rPr><w:ins w:id="3" w:author="本人"/></w:rPr></w:pPr>')
               + p(dele('消す段落'), mark=gone) + p(r('前半'), mark=gone) + p(r('後半')), comments=True)
    out = C.clean(raw, accept=True)
    assert C.pending_suggestions(out) == 0 and 'word/comments.xml' not in zipfile.ZipFile(io.BytesIO(out)).namelist()
    assert C.texts(out) == ['見出し', '最初の文章。', '足した段落', '前半後半']
    assert ''.join(C.texts(out)) == ''.join(C.texts(raw, 'after'))

def test_changes_since_last_delivery_become_whole_phrase_suggestions():
    base = ['見出し', '最初にかかるお金は、ページと広告の数十万円だけです。', '消える段落', '残る段落']
    new = docx(p(r('見出し', True)) + p(r('最初にかかるお金は、'), r('数万円の広告費くらいです。', True)) + p(r('残る段落')) + p(r('新しい段落')))
    out, changed = C.tracked(base, new, 'パイナ')
    assert changed >= 2
    assert C.texts(out, 'after') == ['見出し', '最初にかかるお金は、数万円の広告費くらいです。', '残る段落', '新しい段落']
    assert C.texts(out, 'before') == base
    xml = zipfile.ZipFile(io.BytesIO(out)).read('word/document.xml').decode()
    assert '<w:b />' in xml or '<w:b/>' in xml  # run formatting survives the rewrite
    segs = C._segments('ページと広告の数十万円だけです。', '数万円の広告費くらいです。')
    assert all(len(v) > 1 for k, v, _ in segs if k != 'eq')  # no one-character fragments


def test_adopting_an_older_copy_makes_its_current_text_the_base(tmp_path, monkeypatch):
    import json
    from app.services import gdoc_events as E, gdoc_drive as G
    monkeypatch.setattr(E, 'ROOT', tmp_path)
    monkeypatch.setattr(G, 'comments', lambda *a: [])
    monkeypatch.setattr(G, 'export_docx', lambda *a: docx(p(r('お客さんが赤字を入れた文'))))
    assert C.adopt('acct', 'work', 'client')['paragraphs'] == 1
    meta = json.loads((tmp_path/'client'/'client'/'meta.json').read_text())
    assert meta['published_after'] == ['お客さんが赤字を入れた文'] and meta['work'] == 'work'
    monkeypatch.setattr(G, 'export_docx', lambda *a: docx(p(ins('提案'))))
    import pytest
    with pytest.raises(ValueError): C.adopt('acct', 'work', 'client')

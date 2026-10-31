from types import SimpleNamespace
from app.services import phone_control as P


def test_partial_read_preserves_full_screen_refs_and_duplicate_matches(monkeypatch):
    xml = '<hierarchy>' + ''.join(f'<node text="{label}" class="Button" clickable="true" package="test" bounds="[0,0][100,40]" />' for label in ['戻る','保存','保存']) + '</hierarchy>'
    monkeypatch.setattr(P,'_fast',lambda serial:SimpleNamespace(dump_hierarchy=lambda **kw:xml))
    result=P.read('test','保存')
    assert '@p1' not in result and '@p2' in result and '@p3' in result
    assert len(P._screens['test']) == 3
    assert P._target('test','@p2',None)['name']=='保存'
    assert '一致なし' in P.read('test','非表示の項目')

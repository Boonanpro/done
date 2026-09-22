import pytest
from app.services.editor_consultation_sheet import empty, update, FIELDS

def change(field,value,status='confirmed'):
    return {'field':field,'status':status,'value':value}

def test_eight_fields_and_unknown_is_not_undecided():
    sheet=empty()
    assert len(sheet['fields'])==8
    assert all(v['status']=='unknown' for v in sheet['fields'].values())
    filled=update(sheet,[change('subject','シミュレーション仮説'),change('platform','YouTube'),change('duration','下書きを見て決める','undecided')])
    assert filled['fields']['purpose']['status']=='unknown'
    assert filled['fields']['duration']['status']=='undecided'
    assert not filled['ready_for_draft']
    assert sheet==empty()

def test_ready_requires_all_fields_and_reference_agreement():
    sheet=update(None,[change(key,'相談して未定で進める','undecided') for key in FIELDS])
    assert not sheet['ready_for_draft']
    sheet=update(sheet,[],True)
    assert sheet['ready_for_draft']
    changed=update(sheet,[change('references','別の候補を探す','undecided')])
    assert not changed['reference_agreed'] and not changed['ready_for_draft']

def test_bad_old_memo_is_not_promoted_and_correction_preserves_other_fields():
    sheet=update({'version':2,'facts':{'direction':['simulation hypothesis']}},[change('subject','シミュレーション仮説'),change('platform','YouTube')])
    sheet=update(sheet,[change('subject','フェルミのパラドックス')])
    assert sheet['fields']['subject']['value']=='フェルミのパラドックス'
    assert sheet['fields']['platform']['value']=='YouTube'
    assert sheet['fields']['references']['status']=='unknown'

@pytest.mark.parametrize('entry',[change('position','first'),change('purpose','','confirmed'),change('purpose','x','guess')])
def test_invalid_patch_rejected(entry):
    with pytest.raises(ValueError):update(None,[entry])

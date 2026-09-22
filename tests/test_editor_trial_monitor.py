import json
from scripts.monitor_editor_trial import read_events,summarize


def test_interleaved_inputs_link_by_identity_and_leave_unknown_unlinked():
    base={'room_id':'room','content_id':'content','source_file':'/tmp/room/assistant/events/test.jsonl','source_line':1}
    rows=[
        {'type':'user_transcript','item_id':'a','text':'complete original words','at':100},
        {'type':'visual_decision_started','input_id':'a','input_text':'complete original','decision_id':'d','at':200},
        {'type':'user_transcript','item_id':'b','text':'different request','at':300},
        {'type':'visual_decision_finished','decision_id':'d','action':'compare','available':True,'elapsed_ms':210,'at':450},
        {'type':'reference_library_displayed','input_id':'a','ok':True,'selected_library_ids':['r'],'at':500},
        {'type':'reference_library_displayed','ok':True,'at':510},
        {'type':'live_backend_started','input_id':'b','turn_id':'a'*32,'at':550},
        {'type':'live_presentation_delivered','turn_id':'a'*32,'presentation_id':'p','at':600}]
    result=summarize([{**base,**r} for r in rows])
    a,b=result['inputs']
    assert a['text']=='complete original words'
    assert a['decisions'][0]['request_to_response_ms']==250
    assert len(a['displays'])==1 and not b['displays']
    assert b['reports'][0]['presentation_id']=='p'
    assert len(result['unlinked_events'])==1


def test_partial_tail_is_retried_and_complete_malformed_line_is_reported(tmp_path):
    path=tmp_path/'room/assistant/events/call.jsonl';path.parent.mkdir(parents=True)
    first={'type':'disconnected','at':100,'reason':'user'}
    path.write_text(json.dumps(first)+'\n{',encoding='utf8')
    events,errors=read_events([path]);assert len(events)==1 and not errors
    with path.open('a',encoding='utf8') as f:f.write('"type":"visual_decision_failed","at":200}\ninvalid\n')
    events,errors=read_events([path]);assert len(events)==2 and len(errors)==1
    result=summarize(events,errors)
    assert result['connections'][0]['reason']=='user'
    assert result['failures'][0]['type']=='visual_decision_failed'
    assert result['malformed_lines'][0]['line']==3

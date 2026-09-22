from scripts.inspect_discovery_references import valid_observation,parse_observation

def fixture():
    return {'accessible':True,'summary':'Observed footage','observations':[
        {'start':n*3,'end':n*3+2,'visual':'Person','motion':'Walks','audio':'Music'} for n in range(3)]}

def test_rejects_out_of_bounds_and_non_finite_times():
    value=fixture()
    assert valid_observation(value,10)
    assert not valid_observation(value,4)
    value['observations'][0]['end']=float('nan')
    assert not valid_observation(value,10)

def test_inaccessible_is_not_a_visual_observation():
    assert not valid_observation({'accessible':False})
    assert not valid_observation({'accessible':True,'summary':'Title guess','observations':[]})

def test_extracts_result_after_non_result_prose():
    assert parse_observation('analysis {} then {"accessible":false}')=={'accessible':False}

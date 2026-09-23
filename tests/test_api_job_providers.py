import json

from app.services.api_job_providers import _args


def test_deepseek_markup_inside_an_argument_is_split_back_into_parameters():
    """2026-09-23 EX seat job: the action value carried DeepSeek's own tool markup and the call failed."""
    raw = json.dumps({'action': 'evaluate">\n<｜｜DSML｜｜ parameter name="expression" string="true">(() => document.title)()</｜｜DSML｜｜parameter>'})
    assert _args(raw) == {'action': 'evaluate', 'expression': '(() => document.title)()'}


def test_ordinary_and_broken_arguments():
    assert _args('{"action": "click", "ref": "@e3"}') == {'action': 'click', 'ref': '@e3'}
    assert _args('not json') == {} and _args('') == {} and _args('[1]') == {}

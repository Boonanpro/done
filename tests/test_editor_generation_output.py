from app.timeline_mcp_server import _generated_image_url
from app.timeline_mcp_server import _find_generated_video_url


def test_cli_result_url_beats_reference_input():
    result=[{'status':'completed','result_url':'https://example.test/generated.png',
             'params':{'medias':[{'data':{'url':'https://example.test/reference.png'}}]}}]
    assert _generated_image_url(result)=='https://example.test/generated.png'


def test_pending_job_input_is_not_a_result():
    assert _generated_image_url({'status':'queued','params':{'medias':[{'url':'https://example.test/input.png'}]}}) is None


def test_video_output_wins_over_input_and_thumbnail():
    payload={'params':{'medias':[{'url':'https://example.test/input.jpg'}]},
             'thumbnail':{'url':'https://example.test/thumb.jpg'},
             'result_url':'https://example.test/movie.mp4'}
    assert _find_generated_video_url(payload)=='https://example.test/movie.mp4'


def test_video_pending_and_reference_only_have_no_output():
    assert _find_generated_video_url({'params':{'medias':[{'url':'https://example.test/input.mp4'}]}}) is None
    assert _find_generated_video_url({'status':'processing','result_url':'https://example.test/movie.mp4'}) is None

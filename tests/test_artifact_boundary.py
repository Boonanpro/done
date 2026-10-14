import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import artifact_boundary as ab  # noqa: E402

SLUGS = {'x-operation', 'script-room', 'kittoku'}


def reasons(found):
    return [f.reason for f in found]


def test_the_2026_10_14_leak_is_caught():
    assert reasons(ab.path_findings('app/api/x_operation_routes.py', SLUGS)) == ['Dan file named after site x-operation']
    assert ab.path_findings('frontend/src/app/api/x-operation/editorial/route.ts', SLUGS)
    assert reasons(ab.line_findings('app/api/x.py', 'ROOM = "dc33f0c1-d8f1-4786-88a9-564efc407fed"', SLUGS)) == ['fixed room ID constant']
    assert reasons(ab.line_findings('app/api/x.py', "SITE = 'https://dan-site-x-operation-3ef49fba.vercel.app'", SLUGS))[0] == 'dedicated site host'
    assert reasons(ab.line_findings('frontend/src/lib/a.ts', "fetch('/preview/script-room/editorial')", SLUGS)) == ['path into site script-room']


def test_site_folders_and_generic_code_pass():
    assert not ab.path_findings('frontend/src/app/artifacts/x-operation/_server/routes.py', SLUGS)
    assert not ab.line_findings('frontend/src/app/artifacts/x-operation/_server/routes.py', 'ROOM = "dc33f0c1-d8f1-4786-88a9-564efc407fed"', SLUGS)
    assert not ab.path_findings('frontend/src/app/api/v1/chat/x/route.ts', SLUGS)
    assert not ab.path_findings('app/services/artifact_backends.py', SLUGS)
    assert not ab.line_findings('app/services/a.py', "path = ARTIFACTS/slug/'_server'", SLUGS)
    assert not ab.line_findings('app/services/a.py', "'/preview/x-operation'  # artifact-boundary: ok", SLUGS)
    assert not ab.line_findings('frontend/src/lib/custom-domain-rewrites.generated.ts', "'/artifacts/kittoku'", SLUGS)


def test_changes_to_older_files_are_judged_by_their_lines():
    assert not ab.path_findings('frontend/src/app/api/voice-note/editorial/route.ts', SLUGS, added=False)
    assert not ab.path_findings('app/api/x_operation_routes.py', SLUGS, added=False)

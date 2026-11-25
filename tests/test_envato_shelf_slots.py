import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import envato_shelf as e


class AeSlotTests(unittest.TestCase):
    def test_only_one_render_holds_after_effects_at_a_time(self):
        with tempfile.TemporaryDirectory() as d, patch.object(e, 'SHELF', Path(d)), patch.object(e, 'SLOTS', 1), \
                patch('time.sleep', lambda s: threading.Event().wait(0.01)):
            inside, peak, lock = [0], [0], threading.Lock()
            def work():
                with e._slot():
                    with lock:
                        inside[0] += 1; peak[0] = max(peak[0], inside[0])
                    threading.Event().wait(0.05)
                    with lock:
                        inside[0] -= 1
            threads = [threading.Thread(target=work) for _ in range(3)]
            [t.start() for t in threads]; [t.join() for t in threads]
        self.assertEqual(peak[0], 1)

    def test_orphans_are_render_cores_of_gone_folders_and_adopted_workers(self):
        with tempfile.TemporaryDirectory() as d, patch.object(e, 'SHELF', Path(d)):
            live = Path(d, 'render-live'); live.mkdir()
            app = '/Applications/Adobe After Effects 2027/Adobe After Effects 2027.app/Contents/'
            rows = [(10, 1, app + f'aerendercore.app/Contents/MacOS/aerendercore -noui -project {d}/render-gone/render.aep -rqindex 1'),
                    (11, 1, app + f'aerendercore.app/Contents/MacOS/aerendercore -noui -project {live}/render.aep -rqindex 1'),
                    (12, 1, app + 'MacOS/After Effects -m -noui -ApplePersistenceIgnoreState YES'),
                    (13, 500, app + 'MacOS/After Effects -m -noui -ApplePersistenceIgnoreState YES'),
                    (14, 1, app + 'MacOS/After Effects')]
            killed = []
            with patch.object(e, '_ps', return_value=rows), patch.object(e, '_kill', killed.append):
                self.assertEqual(e.sweep_orphans(), [10, 12])
        self.assertEqual(killed, [10, 12])

    def test_render_core_is_stopped_with_the_render(self):
        project = Path('/tmp/render-x/render.aep')
        class Proc:
            args, returncode, stderr = ['aerender'], 0, None
            def __init__(self): self.n = 0
            def poll(self):
                self.n += 1
                return None if self.n < 2 else 0
            def kill(self): pass
            def wait(self): pass
        killed, reniced = [], []
        with patch('subprocess.Popen', return_value=Proc()), patch.object(e, '_cores_for', return_value=[77]), \
                patch.object(e, '_kill', killed.append), patch('time.sleep'), \
                patch('subprocess.run', lambda args, **k: reniced.append(args)):
            e._aerender(project)
        self.assertEqual(killed, [77])
        self.assertEqual(reniced, [['renice', '15', '-p', '77']])


if __name__ == '__main__':
    unittest.main()

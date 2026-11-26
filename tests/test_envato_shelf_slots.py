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

    def test_orphans_are_renders_whose_caller_ended_and_their_cores(self):
        with tempfile.TemporaryDirectory() as d, patch.object(e, 'SHELF', Path(d)):
            ae = '/Applications/Adobe After Effects 2027/'
            app = ae + 'Adobe After Effects 2027.app/Contents/'
            core = app + 'aerendercore.app/Contents/MacOS/aerendercore -noui -project {}/render.aep -rqindex 1'
            wrap = ae + 'aerender -project {}/render.aep -rqindex 1'
            rows = [(20, 1, wrap.format(f'{d}/render-left')),        # caller ended (2026-11-25), folder still there
                    (21, 20, wrap.format(f'{d}/render-left')),       # the aerender it started
                    (22, 1, core.format(f'{d}/render-left')),
                    (30, 500, wrap.format(f'{d}/render-live')),      # Python 500 is still waiting on it
                    (31, 30, wrap.format(f'{d}/render-live')),
                    (32, 1, core.format(f'{d}/render-live')),
                    (10, 1, core.format(f'{d}/render-gone')),        # nothing renders it any more
                    (12, 1, app + 'MacOS/After Effects -m -noui -ApplePersistenceIgnoreState YES'),
                    (13, 500, app + 'MacOS/After Effects -m -noui -ApplePersistenceIgnoreState YES'),
                    (14, 1, app + 'MacOS/After Effects')]           # the one the owner opens on screen
            killed = []
            with patch.object(e, '_ps', return_value=rows), patch.object(e, '_kill', killed.append):
                stopped = e.sweep_orphans()
        self.assertEqual(sorted(stopped), [10, 12, 20, 21, 22])
        self.assertEqual(sorted(killed), [10, 12, 20, 21, 22])

    def test_scratch_folders_go_only_when_unused_and_quiet(self):
        import os
        with tempfile.TemporaryDirectory() as d, patch.object(e, 'SHELF', Path(d)):
            old, busy, fresh = (Path(d, n) for n in ('render-old', 'render-busy', 'render-fresh'))
            for f in (old, busy, fresh):
                f.mkdir(); (f / 'render.aep').write_text('x')
            for f in (old, busy):
                for x in (f, f / 'render.aep'):
                    os.utime(x, (time.time() - 3 * 3600,) * 2)
            rows = [(5, 1, f'aerendercore -project {busy}/render.aep')]
            with patch.object(e, '_ps', return_value=rows):
                removed = e.sweep_scratch()
            self.assertEqual(removed, [old])
            self.assertFalse(old.exists()); self.assertTrue(busy.exists()); self.assertTrue(fresh.exists())

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


def test_a_slow_process_list_finds_nothing_instead_of_ending_the_render(monkeypatch):
    import subprocess
    from app.services import envato_shelf as e
    def slow(*a, **k): raise subprocess.TimeoutExpired(a[0], k.get('timeout'))
    monkeypatch.setattr(e.subprocess, 'run', slow)
    assert e._ps() == [] and e.sweep_orphans() == []

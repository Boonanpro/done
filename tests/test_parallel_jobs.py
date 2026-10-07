import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app.services import command_job_state as state
from app.services import parallel_job_runner as runner
from app.services import work_locks


class _TempRoots(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [patch.object(state, 'ROOT', root), patch.object(work_locks, 'ROOT', root),
                        patch.object(work_locks, 'LOCKS', root / 'locks')]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def job(self, **fields):
        job_id = str(uuid.uuid4())
        state.create(job_id, user_id='U', room_id='R', origin_room_id='R', task='調査して', engine='parallel',
                     model='opus', title='調査', **fields)
        return job_id


class WorkLockTests(_TempRoots):
    def test_one_file_one_holder_until_released(self):
        key = work_locks.file_key(r'D:\dan-workspace\site\index.html')
        self.assertTrue(key.startswith('file:'))
        self.assertIsNone(work_locks.try_acquire(key, 'room:A', 'A'))
        self.assertIsNone(work_locks.try_acquire(key, 'room:A', 'A'))   # already ours
        self.assertEqual(work_locks.try_acquire(key, 'room:B', 'B')['owner'], 'room:A')
        work_locks.release_owner('room:A')
        self.assertIsNone(work_locks.try_acquire(key, 'room:B', 'B'))

    def test_temp_and_own_folder_are_never_held(self):
        self.assertEqual(work_locks.file_key(r'C:\Users\Owner\AppData\Local\Temp\x.txt'), '')
        self.assertEqual(work_locks.file_key('D:/dan-workspace/jobs/abcd1234/out.mp4', 'D:/dan-workspace/jobs/abcd1234'), '')
        self.assertEqual(work_locks.tool_key('browser', {'action': 'open'}), '')
        self.assertEqual(work_locks.tool_key('phone', {}), 'device:phone')

    def test_finished_job_and_idle_room_no_longer_hold(self):
        job_id = self.job()
        key = 'device:desktop'
        self.assertIsNone(work_locks.try_acquire(key, 'job:' + job_id, '調査'))
        self.assertIsNotNone(work_locks.try_acquire(key, 'room:B'))
        state.change(job_id, lambda s: s.update(state='completed'))
        self.assertIsNone(work_locks.try_acquire(key, 'room:B'))
        record = json.loads(work_locks._path(key).read_text(encoding='utf-8'))
        record['touched'] = time.time() - work_locks.ROOM_TTL - 1
        work_locks._path(key).write_text(json.dumps(record), encoding='utf-8')
        self.assertIsNone(work_locks.try_acquire(key, 'job:' + self.job()))

    def test_waiting_gives_up_and_names_the_holder(self):
        key = work_locks.file_key(r'D:\dan-workspace\a.txt')
        work_locks.try_acquire(key, 'room:A', 'LPの修正')
        seen = []
        other = work_locks.acquire(key, 'room:B', 'B', on_wait=seen.append, limit=0)
        self.assertEqual(other['owner'], 'room:A')
        self.assertEqual(len(seen), 1)
        self.assertIn('「LPの修正」の完了待ち（a.txt）', work_locks.waiting_text(other))
        self.assertEqual(work_locks.wait_limit('room:x'), 60)

    def test_job_shows_what_it_waits_for(self):
        job_id = self.job()
        work_locks.note_waiting('job:' + job_id, {'owner': 'room:A', 'title': 'LPの修正', 'key': 'device:phone'})
        self.assertEqual(runner.public(state.read(job_id))['state'], 'waiting')
        work_locks.clear_waiting('job:' + job_id)
        self.assertEqual(runner.public(state.read(job_id))['state'], 'queued')


class ParallelJobTests(_TempRoots):
    def test_model_words(self):
        self.assertEqual([runner.model_key(v) for v in ('GPT-6', 'gpt-6-astra', 'Opus', 'Fable', 'claude', '')],
                         ['astra', 'astra', 'opus', 'fable', 'opus', ''])

    def test_room_list_has_this_rooms_parallel_jobs_only(self):
        mine = self.job()
        state.create(str(uuid.uuid4()), user_id='U', room_id='R', origin_room_id='R', task='x', engine='cli')
        state.create(str(uuid.uuid4()), user_id='U', room_id='OTHER', origin_room_id='R', task='x', engine='parallel')
        self.assertEqual([s['id'] for s in runner.room_jobs('U', 'R')], [mine])
        row = runner.public(state.read(mine))
        self.assertEqual((row['model_label'], row['state_label'], row['active']), ('Opus', '開始待ち', True))

    def test_title_is_the_first_line(self):
        self.assertEqual(runner.title_of('\nX運用の調査\n詳しく'), 'X運用の調査')
        self.assertTrue(runner.title_of('あ' * 100).endswith('…'))


if __name__ == '__main__':
    unittest.main()

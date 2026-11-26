import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import room_reports


class RoomReportsTests(unittest.TestCase):
    def test_reports_after_the_last_turn_reach_the_rooms_dan(self):
        from app.api import chat_routes
        with tempfile.TemporaryDirectory() as d, patch.object(room_reports, 'ROOT', Path(d)):
            room_reports.add('r1', source_title='制作: 中村さん', source_room_id='p2', text='割り当て表を作りました')
            lines = chat_routes._room_reports('r1', None)
            self.assertEqual(len(lines), 1)
            self.assertIn('割り当て表を作りました', lines[0])
            self.assertIn('/chat/p2', lines[0])
            # Read with a later turn: already seen
            self.assertEqual(chat_routes._room_reports('r1', '2999-01-01T00:00:00+00:00'), [])
            self.assertEqual(chat_routes._room_reports('other', None), [])

    def test_old_reports_are_dropped(self):
        with tempfile.TemporaryDirectory() as d, patch.object(room_reports, 'ROOT', Path(d)):
            room_reports.add('r1', source_title='a', source_room_id='p', text='old')
            with patch('time.time', return_value=time.time() + room_reports.KEEP_SECONDS + 60):
                self.assertEqual(room_reports.since('r1', 0), [])
            self.assertEqual(Path(d, 'r1.jsonl').read_text(), '')

    def test_room_id_cannot_escape_the_folder(self):
        with self.assertRaises(ValueError):
            room_reports.add('../x', source_title='', source_room_id='', text='t')


if __name__ == '__main__':
    unittest.main()

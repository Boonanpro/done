import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.services.message_media import normalize


class NormalizeTests(unittest.TestCase):
    def test_bare_paths_become_attachments(self):
        out = normalize('- シート: /api/v1/files/a.pdf\n- 画像: /api/v1/files/b.png\n- 動画 /api/v1/files/c.mp4')
        self.assertIn('[添付ファイル: a.pdf (/api/v1/files/a.pdf)]', out)
        self.assertIn('[添付画像: /api/v1/files/b.png]', out)
        self.assertIn('[添付動画: c.mp4 (/api/v1/files/c.mp4)]', out)

    def test_pc_address_and_upload_folder(self):   # the report of 2026-09-27 05:38
        out = normalize('開いたURL: `http://127.0.0.1:3000/api/v1/files/a.pdf`（実体は `D:/done/uploads/a.pdf`）')
        self.assertEqual(out.count('[添付ファイル: a.pdf (/api/v1/files/a.pdf)]'), 1)
        self.assertNotIn('127.0.0.1', out)

    def test_existing_attachment_links_and_code_are_kept(self):
        text = '[添付画像: /api/v1/files/a.png]\n[資料](/api/v1/files/q.pdf)\n```\ncurl /api/v1/files/z.png\n```'
        self.assertEqual(normalize(text), text)
        self.assertEqual(normalize('[資料](http://localhost:3000/api/v1/files/q.pdf)'), '[資料](/api/v1/files/q.pdf)')

    def test_already_attached_file_is_not_attached_twice(self):
        out = normalize('ファイルは `/api/v1/files/x.pdf` です\n[添付ファイル: シート.pdf (/api/v1/files/x.pdf)]')
        self.assertEqual(out.count('/api/v1/files/x.pdf'), 1)

    def test_plain_text_untouched(self):
        self.assertEqual(normalize('普通の文 https://example.com/a.png'), '普通の文 https://example.com/a.png')


class SameRoomTests(unittest.TestCase):
    def test_request_copy_only_when_asked_from_another_room(self):
        from app.services.command_job_runner import relay_request
        chat = AsyncMock(); chat.send_message.return_value = {'id': 'm'}
        row = {'room_id': 'R', 'user_id': 'U'}
        self.assertIsNone(asyncio.run(relay_request(chat, row, {'origin_room_id': 'R', 'task': 't'}, 'j')))
        chat.send_message.assert_not_called()
        from app.services.voice_parts import VOICE_TASK
        task = '今回のユーザー発言（原文）:\nシートを直して\n参考の直前会話（過去の発言は…）:\n[]' + VOICE_TASK
        asyncio.run(relay_request(chat, row, {'origin_room_id': 'C', 'task': task}, 'j'))
        posted = chat.send_message.call_args.args[2]
        self.assertEqual(posted, '【あなたの依頼・Done経由】\nシートを直して')

    def test_same_room_report_has_no_heading_or_link(self):
        from app.services import command_center
        chat = AsyncMock(); chat.get_room.return_value = {'id': 'R'}
        chat.send_message.return_value = {'id': 'm'}
        projects = AsyncMock()
        project = {'id': 'P', 'room_id': 'R', 'user_id': 'U', 'title': '部屋'}
        projects.get_project.return_value = project
        projects.get_project_by_room_id.return_value = project
        with patch.object(command_center, 'ChatService', return_value=chat), \
             patch.object(command_center, 'ProjectService', return_value=projects):
            asyncio.run(command_center.execute({'action': 'report', 'project_id': 'P', 'task': '結果'}, 'R', 'U'))
        self.assertEqual(chat.send_message.call_args.args[2], '結果')


class VoiceTranscriptTests(unittest.TestCase):
    def test_backchannel_and_segment_start(self):
        from app.api.voicelog_routes import voice_text, is_backchannel
        self.assertTrue(is_backchannel(voice_text('はい。はい。')))
        self.assertTrue(is_backchannel(voice_text('うん。なるほど。')))
        self.assertFalse(is_backchannel(voice_text('わかりました。直します。')))
        self.assertEqual(voice_text('、スマホでポルノ'), 'スマホでポルノ')

    def test_quiet_seconds_marks_a_stuck_job(self):
        from datetime import datetime, timedelta, timezone
        from app.services.voice_parts import quiet_seconds, work_status
        old = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        self.assertGreater(quiet_seconds({'updated_at': old}), 1100)
        row = work_status([{'id': 'j', 'state': 'running', 'task': 't', 'events': [], 'updated_at': old}])['work_status'][0]
        self.assertEqual(row['id'], 'j')
        self.assertGreater(row['最後に動いてから(秒)'], 1100)


if __name__ == '__main__':
    unittest.main()

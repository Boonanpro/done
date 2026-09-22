import unittest
from unittest.mock import patch, MagicMock
from app.services.command_cards import outbound_cards


class CardTests(unittest.IsolatedAsyncioTestCase):
    async def test_sent_state_survives_even_when_chat_still_says_draft(self):
        service = MagicMock()
        service.list_for_room.return_value = [{'id': 'card', 'status': 'sent', 'content': 'Latest edited reply',
                                              'action_data': {'sent_at': '2026-09-14T09:28:33+00:00', 'sent_by': 'user'}}]
        with patch('app.services.command_cards.OutboundMessageService', return_value=service):
            result = await outbound_cards('authorized-room')
        self.assertEqual(result['cards'][0]['status'], 'sent')
        self.assertEqual(result['cards'][0]['sent_by'], 'user')
        self.assertEqual(result['cards'][0]['sent_at'], '2026-09-14T18:28:33+09:00')
        service.list_for_room.assert_called_once_with('authorized-room', limit=20)

    async def test_read_failure_is_not_an_empty_pending_list(self):
        with patch('app.services.command_cards.OutboundMessageService', side_effect=RuntimeError('offline')):
            result = await outbound_cards('room')
        self.assertIn('error', result)

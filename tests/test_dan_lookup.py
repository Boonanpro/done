"""lookup (read Dan's own data) and wait_until (wait for a condition): the fixed forms of throwaway Python and sleep."""
import asyncio
import http.server
import socket
import threading
from email.message import EmailMessage
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import dan_lookup
from app.agent.v2.tools import execute_tool, format_tool_result, parse_tool_name

USER, ROOM = 'user-1', 'room-1'


def text(result):
    return result.get('output') or result.get('error') or ''


@pytest.mark.asyncio
async def test_messages_recent_search_period_and_single(monkeypatch):
    rows = [{'id': 'm1', 'created_at': '2026-09-01T01:00:00.21366+00:00', 'sender_type': 'user', 'content': '税理士に返信して'},
            {'id': 'm2', 'created_at': '2026-09-10T10:00:00+09:00', 'sender_type': 'ai', 'content': 'あ'*900}]
    chat = MagicMock(); chat.get_messages = AsyncMock(return_value=rows); chat.search_messages = AsyncMock(return_value=rows[:1])
    monkeypatch.setattr('app.services.chat_service.ChatService', lambda: chat)
    recent = await dan_lookup.lookup({'source': 'messages'}, USER, ROOM)
    assert recent['count'] == 2 and '全900字' in text(recent)
    chat.get_messages.assert_awaited_with(ROOM, USER, limit=30)          # this room, this user
    found = await dan_lookup.lookup({'source': 'messages', 'query': '税理士', 'room_id': 'other'}, USER, ROOM)
    chat.search_messages.assert_awaited_with('other', USER, '税理士', limit=30)
    assert found['count'] == 1
    period = await dan_lookup.lookup({'source': 'messages', 'since': '2026-09-05'}, USER, ROOM)
    assert period['count'] == 1 and 'm2' in text(period)
    one = await dan_lookup.lookup({'source': 'messages', 'id': 'm2'}, USER, ROOM)
    assert 'あ'*900 in text(one)
    bad = await dan_lookup.lookup({'source': 'messages', 'since': 'きのう'}, USER, ROOM)
    assert bad['success'] is False and '日時の形式' in bad['error']


class FakeImap:
    def __init__(self):
        m = EmailMessage(); m['From'] = 'Kim <kim@example.test>'; m['To'] = 'me@example.test'; m['Subject'] = '源泉所得税の件'
        m['Date'] = 'Mon, 01 Sep 2026 10:00:00 +0900'; m.set_content('納期限は10日です。')
        self.raw = m.as_bytes(); self.searched = None
    def list(self): return 'OK', [b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"']
    def select(self, folder, readonly=True): self.folder = folder; return 'OK', [b'1']
    def uid(self, command, *args):
        if command == 'search':
            self.searched = args; return 'OK', [b'7']
        if 'HEADER' in args[1]:  # list view: real servers answer the two parts in their own order (text first on Gmail)
            blank = bytes([10, 10])
            head = self.raw.split(blank)[0]+blank
            return 'OK', [(b'7 (UID 7 BODY[TEXT]<0> {20}', '納期限は10日です。'.encode()), (b' BODY[HEADER.FIELDS (FROM TO DATE SUBJECT)] {90}', head), b')']
        return 'OK', [(b'7 (BODY[] {300}', self.raw), b')']
    def logout(self): self.closed = True


@pytest.mark.asyncio
async def test_mail_list_folder_and_full_text(monkeypatch):
    imap = FakeImap()
    monkeypatch.setattr('app.services.imap_email_service.connect_mailbox', lambda key: imap)
    listed = await dan_lookup.lookup({'source': 'mail', 'mailbox': 'gmail', 'folder': 'sent', 'to': 'kim@example.test'}, USER, ROOM)
    assert listed['count'] == 1 and 'uid=7' in text(listed) and '源泉所得税の件' in text(listed)
    assert imap.folder == '"[Gmail]/Sent Mail"' and 'TO' in imap.searched and imap.closed
    full = await dan_lookup.lookup({'source': 'mail', 'mailbox': 'gmail', 'id': '7'}, USER, ROOM)
    assert '納期限は10日です。' in text(full)


@pytest.mark.asyncio
async def test_other_sources_are_scoped_and_failures_are_explained(monkeypatch):
    artifacts = MagicMock(); artifacts.list = AsyncMock(return_value=[{'id': 'a1', 'label': 'moonbox LP', 'room_id': ROOM, 'created_at': '2026-09-01', 'shared_url': 'https://x.example'}])
    monkeypatch.setattr('app.services.chat_artifact_service.ChatArtifactService', lambda: artifacts)
    found = await dan_lookup.lookup({'source': 'artifacts', 'query': 'moonbox'}, USER, ROOM)
    assert found['count'] == 1 and 'https://x.example' in text(found)
    artifacts.list.assert_awaited_with(USER, room_id=None, limit=50)
    monkeypatch.setattr('app.services.followups.list_watches', lambda room: [{'id': 'w1', 'kind': 'mail', 'fire_at': '2026-09-22', 'room_id': room, 'plain_note': '税理士メール', 'spec': {'mail_from': 'kim'}}])
    watches = await dan_lookup.lookup({'source': 'watches'}, USER, ROOM)
    assert 'room=room-1' in text(watches) and 'mail_from' in text(watches)
    everything = await dan_lookup.lookup({'source': 'watches', 'all_rooms': True}, USER, ROOM)
    assert 'room=None' in text(everything)
    inquiries = MagicMock(); inquiries.list = AsyncMock(side_effect=RuntimeError('db down'))
    monkeypatch.setattr('app.services.inquiry_service.InquiryService', lambda: inquiries)
    failed = await dan_lookup.lookup({'source': 'inquiries', 'scope': 'himawari'}, USER, ROOM)
    assert failed['success'] is False and 'db down' in failed['error']
    assert (await dan_lookup.lookup({'source': 'passwords'}, USER, ROOM))['success'] is False


@pytest.mark.asyncio
async def test_tools_are_reachable_through_the_shared_tool_layer(monkeypatch):
    chat = MagicMock(); chat.get_messages = AsyncMock(return_value=[{'id': 'm1', 'created_at': '2026-09-01T10:00:00+09:00', 'sender_type': 'user', 'content': 'こんにちは'}])
    monkeypatch.setattr('app.services.chat_service.ChatService', lambda: chat)
    skill, action = parse_tool_name('lookup')
    # The same call shape app/mcp_server.py uses for every backend (Claude CLI, Codex CLI, voice-delegated jobs).
    result = await execute_tool(tool_call={'tool_use_id': 'mcp_lookup', 'skill': skill, 'action': action, 'params': {'source': 'messages'}},
                                user_id=USER, session_id=ROOM)
    assert 'こんにちは' in format_tool_result(result, skill, action).text


@pytest.mark.asyncio
async def test_wait_until_returns_the_moment_the_condition_holds(tmp_path):
    target = tmp_path/'render.mp4'
    async def produce():
        await asyncio.sleep(.6); target.write_bytes(b'x'*2048)
    task = asyncio.create_task(produce())
    done = await dan_lookup.wait_until({'path': str(target), 'min_bytes': 1024, 'stable': True, 'timeout_seconds': 10})
    await task
    assert done['success'] and '2048 bytes' in done['output']
    late = await dan_lookup.wait_until({'path': str(tmp_path/'never.json'), 'timeout_seconds': 1})
    assert late['success'] is False and 'missing' in late['error']
    gone = await dan_lookup.wait_until({'path_gone': str(tmp_path/'never.json'), 'timeout_seconds': 1})
    assert gone['success']
    assert (await dan_lookup.wait_until({}))['success'] is False
    assert (await dan_lookup.wait_until({'url': 'file:///etc/passwd'}))['success'] is False


@pytest.mark.asyncio
async def test_wait_until_url_and_port():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"status":"healthy"}')
        def log_message(self, *a): pass
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
    server = http.server.HTTPServer(('127.0.0.1', port), Handler)
    closed = await dan_lookup.wait_until({'port': port, 'closed': True, 'timeout_seconds': 2})
    assert closed['success'] is False or 'closed' in closed.get('output', '')
    threading.Timer(.5, lambda: threading.Thread(target=server.serve_forever, daemon=True).start()).start()
    try:
        up = await dan_lookup.wait_until({'url': f'http://127.0.0.1:{port}/health', 'text': 'healthy', 'timeout_seconds': 10})
        assert up['success']
        assert (await dan_lookup.wait_until({'port': port, 'timeout_seconds': 3}))['success']
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_addresses_lists_the_owners_mailboxes_without_secrets(monkeypatch):
    from unittest.mock import AsyncMock
    from app.services import dan_lookup
    service = AsyncMock()
    service.list_credentials.return_value = [{'service': 'note'}, {'service': 'shop'}, {'service': 'bank'}, {'service': 'robot'}]
    logins = {'note': 'me@example.com', 'shop': 'ME@example.com', 'bank': 'member-0012', 'robot': 'x@proj.iam.gserviceaccount.com'}
    service.get_credential.side_effect = lambda user, name: {'id': logins[name], 'password': 'SECRET'}
    monkeypatch.setattr('app.services.credentials_service.get_credentials_service', lambda: service)
    otp = AsyncMock(); otp.has_imap_access.return_value = True
    monkeypatch.setattr('app.services.otp_service.get_otp_service', lambda: otp)
    out = (await dan_lookup.lookup({'source': 'addresses'}, 'u', None))['output']
    assert 'me@example.com — 2件' in out and 'member-0012' not in out and 'gserviceaccount' not in out and 'SECRET' not in out
    assert '必ず本人に確認' in out

from types import SimpleNamespace
import logging
import pytest

from app.services.collab_service import CollabService
from app.services.collab_link_preview import MetadataParser, public_target


class Duplicate(Exception):
    code = '23505'


class Database:
    def __init__(self):
        self.rows = {}
        self.fail_after_insert = True

    def table(self, name):
        db = self

        class Query:
            operation, value, filters = None, None, None

            def insert(self, value):
                self.operation, self.value = 'insert', value
                return self

            def update(self, value):
                self.operation = 'update'
                return self

            def select(self, value):
                self.operation, self.filters = 'select', {}
                return self

            def eq(self, key, value):
                if self.filters is not None:
                    self.filters[key] = value
                return self

            def execute(self):
                if self.operation == 'insert':
                    if self.value['id'] in db.rows:
                        raise Duplicate()
                    db.rows[self.value['id']] = dict(self.value)
                    if db.fail_after_insert:
                        db.fail_after_insert = False
                        raise OSError('connection reset')
                    return SimpleNamespace(data=[self.value])
                if self.operation == 'select':
                    return SimpleNamespace(data=[r for r in db.rows.values() if all(r[k] == v for k, v in self.filters.items())])
                return SimpleNamespace(data=[])
        return Query()


@pytest.mark.asyncio
async def test_lost_response_and_repeated_send_do_not_duplicate_message():
    service = CollabService.__new__(CollabService)
    service.supabase = Database()
    service.logger = logging.getLogger(__name__)
    args = dict(room_id='test-room', sender_type='guest', sender_name='同じ名前', content='写真です',
                metadata={'sender_id': 'guest-a'}, message_id='stable-message-id')
    first = await service.send_message(**args)
    second = await service.send_message(**args)
    assert first['id'] == second['id']
    assert len(service.supabase.rows) == 1
    assert not first['_replayed'] and second['_replayed']


def test_preview_extracts_title_and_description_without_markup():
    parser = MetadataParser()
    parser.feed('<title>代替</title><meta property="og:title" content="題名 &amp; 内容"><meta name="description" content="説明">')
    assert parser.values['og:title'] == '題名 & 内容'
    assert parser.values['description'] == '説明'


@pytest.mark.parametrize('url', ['https://127.0.0.1', 'https://[::1]', 'http://example.com', 'https://user:pass@example.com', 'https://example.com:8000'])
def test_preview_rejects_internal_or_unsafe_destinations(url):
    with pytest.raises(ValueError):
        public_target(url)

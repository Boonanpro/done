"""
Calendar Service - every connected calendar account of a user (any provider, any number), read together, written to one.

Accounts live in connected_accounts (capability 'calendar'); each provider is a class in calendar_providers. Reading goes
over all of them and says, for each event, which account and calendar it came from (a read that cannot say what it
looked at is not a read). Writing goes to the named account, or the user's default calendar account. One account that
fails (an expired login) is reported and does not hide the others.

2026-09-25: one Google account per user before (connecting the owner's 0aw325171 would have overwritten shub6923, and the
events in 0aw325171 were never seen); no update/delete; reminders not settable; the reading window started at this very
second, so this morning's events were missing from 「今日の予定」.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from app.services import connected_accounts as accounts
from app.services.calendar_providers import provider_class

logger = logging.getLogger(__name__)

CAPABILITY = 'calendar'
JST = timezone(timedelta(hours=9))
# The OAuth return address. It must also be registered with the provider (Google Cloud console > OAuth client).
CALENDAR_REDIRECT_URI = os.environ.get('CALENDAR_REDIRECT_URI', 'http://localhost:8000/api/v1/calendar/callback')
CALENDAR_SCOPES = provider_class('google').SCOPES   # kept for older importers


class CalendarService:
    # ==================== connecting accounts ====================

    def get_auth_url(self, user_id: str, provider: str = 'google', replace_id: Optional[str] = None, hint: Optional[str] = None) -> str:
        """Where to send the user to connect an account. replace_id: this account takes that one's place."""
        state = accounts.sign_state({'u': user_id, 'p': provider, **({'r': replace_id} if replace_id else {})})
        return provider_class(provider).auth_url(state, CALENDAR_REDIRECT_URI, hint)

    async def handle_callback(self, code: str, state: str) -> Tuple[bool, str, Optional[str]]:
        payload = accounts.read_state(state)
        if not payload:
            return False, '連携の有効期限が切れたか、正しくない連携です。もう一度やり直してください。', None
        try:
            cls = provider_class(payload.get('p', 'google'))
            address, token = cls.exchange(code, CALENDAR_REDIRECT_URI)
            accounts.save(payload['u'], cls.provider, address, [CAPABILITY], token, replace_id=payload.get('r'))
            logger.info('Calendar account connected: %s %s', cls.provider, address)
            return True, 'connected', address
        except Exception as e:
            logger.error('Calendar OAuth failed: %s', e)
            return False, str(e), None

    async def get_status(self, user_id: str) -> dict:
        rows = accounts.list_accounts(user_id, CAPABILITY)
        default = accounts.default_account(user_id, CAPABILITY)
        return {'connected': bool(rows), 'email': default['account'] if default else None,
                'accounts': [{'id': r['id'], 'provider': r['provider'], 'account': r['account'], 'label': r.get('label'),
                              'default': CAPABILITY in (r.get('default_for') or [])} for r in rows]}

    async def disconnect(self, user_id: str, account_id: Optional[str] = None) -> bool:
        """Remove one account, or (no id) every calendar account."""
        targets = [account_id] if account_id else [r['id'] for r in accounts.list_accounts(user_id, CAPABILITY)]
        return all(accounts.remove(user_id, t) for t in targets) if targets else False

    def set_default(self, user_id: str, account_id: str) -> bool:
        if not accounts.get(user_id, account_id):
            return False
        accounts.set_default(user_id, account_id, CAPABILITY)
        return True

    # ==================== reading and writing ====================

    def _client(self, user_id: str, row: dict):
        token = accounts.token(user_id, row['id'])
        if token is None:
            raise RuntimeError('連携が無効です')
        return provider_class(row['provider'])(row, token, lambda t: accounts.update_token(user_id, row['id'], t))

    def _pick(self, user_id: str, account: Optional[str]):
        row = accounts.find(user_id, CAPABILITY, account)
        if not row:
            names = ', '.join(r['account'] for r in accounts.list_accounts(user_id, CAPABILITY)) or 'なし'
            raise LookupError(f'カレンダーのアカウント「{account or "既定"}」が見つかりません（連携済み: {names}）。')
        return row, self._client(user_id, row)

    def get_events(self, user_id: str, days: int = 7, max_results: int = 20, account: Optional[str] = None, start_date: Optional[str] = None) -> List[dict]:
        return self.get_events_with_source(user_id, days, max_results, account, start_date)['events']

    def get_events_with_source(self, user_id: str, days: int = 7, max_results: int = 20, account: Optional[str] = None,
                               start_date: Optional[str] = None) -> dict:
        """Events from today 00:00 (local) for `days` days, across every connected account (or the one named), each with
        its account and calendar; the source says which accounts and calendars were read and which could not be."""
        rows = accounts.list_accounts(user_id, CAPABILITY)
        if account:
            one = accounts.find(user_id, CAPABILITY, account)
            rows = [one] if one else []
        if not rows:
            return {'events': [{'error': 'カレンダー未連携。設定画面から連携してください。'}], 'source': None}
        # from start_date (YYYY-MM-DD, past or future: 「24日の予定あった？」 on the 25th is about yesterday), else today 00:00
        start = (datetime.fromisoformat(start_date).replace(tzinfo=JST) if start_date else datetime.now(JST)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=days + (0 if start_date else 1))
        events, read, failed = [], [], []

        def one(row):
            client = self._client(user_id, row)
            return [{**event, 'account': row['account']} for event in client.events(start, end, max_results)], \
                {'account': row['account'], 'provider': row['provider'], 'calendars': [c['name'] for c in client.calendars()[:15]]}
        # the accounts are read at the same time: one after another, two accounts took 3.5 s of a spoken answer (2026-09-25)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(8, len(rows))) as pool:
            futures = [(row, pool.submit(one, row)) for row in rows]
        for row, future in futures:
            try:
                got, info = future.result()
                events.extend(got); read.append(info)
            except Exception as e:
                logger.warning('calendar read failed for %s: %s', row['account'], e)
                failed.append({'account': row['account'], 'error': ('expired' if 'invalid_grant' in str(e) or 'expired' in str(e) else type(e).__name__)})
        events.sort(key=lambda e: e['start'])
        source = {'account': ', '.join(r['account'] for r in read), 'accounts': read, 'calendars': [c for r in read for c in r['calendars']]}
        if failed:
            source['failed'] = failed
        if failed and not read:
            return {'events': [{'error': 'カレンダーを読めませんでした（' + ', '.join(f"{f['account']}: {f['error']}" for f in failed) + '）'}], 'source': source}
        return {'events': events[:max_results * max(1, len(rows))], 'source': source}

    def create_event(self, user_id: str, title: str, start: str, end: str, description: str = '', location: str = '',
                     account: Optional[str] = None, calendar_id: Optional[str] = None, reminders: Optional[list] = None) -> dict:
        try:
            row, client = self._pick(user_id, account)
        except LookupError as e:
            return {'error': str(e)}
        made = client.create(calendar_id, {'title': title, 'start': start, 'end': end, 'description': description or None,
                                           'location': location or None, 'reminders': reminders})
        return {**made, 'account': row['account']}

    def _locate(self, user_id: str, event_id: str, account: Optional[str], calendar_id: Optional[str]):
        """The account and calendar that hold the event (searched when not given)."""
        rows = [accounts.find(user_id, CAPABILITY, account)] if account else accounts.list_accounts(user_id, CAPABILITY)
        for row in [r for r in rows if r]:
            client = self._client(user_id, row)
            for cal in ([calendar_id] if calendar_id else [c['id'] for c in client.calendars()]):
                if client.get(cal, event_id):
                    return row, client, cal
        raise LookupError('その予定が見つかりません（どのアカウントのどのカレンダーにもない）。')

    def update_event(self, user_id: str, event_id: str, account: Optional[str] = None, calendar_id: Optional[str] = None, **fields) -> dict:
        """Change an event: title, start, end, description (the memo), location, reminders (minutes before)."""
        try:
            row, client, cal = self._locate(user_id, event_id, account, calendar_id)
        except LookupError as e:
            return {'error': str(e)}
        return {**client.update(cal, event_id, fields), 'account': row['account']}

    def delete_event(self, user_id: str, event_id: str, account: Optional[str] = None, calendar_id: Optional[str] = None) -> dict:
        try:
            row, client, cal = self._locate(user_id, event_id, account, calendar_id)
        except LookupError as e:
            return {'error': str(e)}
        client.delete(cal, event_id)
        return {'deleted': event_id, 'account': row['account']}

    def find_free_slots(self, user_id: str, days: int = 7) -> List[dict]:
        """Free time (9:00-18:00 JST) over the next days, busy in ANY connected calendar."""
        events = self.get_events(user_id, days=days, max_results=100)
        if events and isinstance(events[0], dict) and 'error' in events[0]:
            return events
        now = datetime.now(JST)
        free_slots = []
        for day_offset in range(days):
            day = now.date() + timedelta(days=day_offset)
            day_start = datetime(day.year, day.month, day.day, 9, 0, tzinfo=JST)
            day_end = datetime(day.year, day.month, day.day, 18, 0, tzinfo=JST)
            if day_start < now:
                day_start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                if day_start >= day_end:
                    continue
            busy = []
            for ev in events:
                try:
                    s = datetime.fromisoformat(ev['start'].replace('Z', '+00:00'))
                    e = datetime.fromisoformat(ev['end'].replace('Z', '+00:00'))
                    if s.tzinfo is None:   # an all-day event (a holiday, a note): not counted as busy, as before
                        continue
                    if s.astimezone(JST).date() == day:
                        busy.append((max(s, day_start), min(e, day_end)))
                except (ValueError, KeyError, TypeError):
                    pass
            cursor = day_start
            for s, e in sorted(busy):
                if cursor < s:
                    free_slots.append({'date': day.isoformat(), 'start': cursor.strftime('%H:%M'), 'end': s.strftime('%H:%M')})
                cursor = max(cursor, e)
            if cursor < day_end:
                free_slots.append({'date': day.isoformat(), 'start': cursor.strftime('%H:%M'), 'end': day_end.strftime('%H:%M')})
        return free_slots


def get_calendar_service() -> CalendarService:
    return CalendarService()

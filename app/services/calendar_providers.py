"""Calendar providers behind one contract, so a user can connect Google, Microsoft, iCloud, CalDAV... accounts side by side.

Each provider class, built for one connected account (connected_accounts row + its token), offers:
    calendars() -> [{'id', 'name', 'primary'}]
    events(start, end, limit) -> [{'id', 'calendar_id', 'calendar', 'title', 'start', 'end', 'location', 'description'}]
    create(calendar_id, fields) / update(calendar_id, event_id, fields) / delete(calendar_id, event_id)
        fields: title, start, end (ISO date or datetime), description, location, reminders (minutes before, list)
and, as class methods, the OAuth steps: auth_url(state, redirect_uri, hint) and exchange(code, redirect_uri) ->
(account address, token dict). Google is implemented; a new provider is one class added to PROVIDERS."""
import os
from datetime import datetime
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app.config import settings

TZ = 'Asia/Tokyo'


def _when(value: str) -> dict:
    return {'date': value} if len(value) <= 10 else {'dateTime': value, 'timeZone': TZ}


class GoogleCalendar:
    provider = 'google'
    SCOPES = ['https://www.googleapis.com/auth/calendar.readonly', 'https://www.googleapis.com/auth/calendar.events']

    @classmethod
    def _config(cls, redirect_uri):
        return {'web': {'client_id': settings.gmail_client_id, 'client_secret': settings.gmail_client_secret,
                        'auth_uri': 'https://accounts.google.com/o/oauth2/auth', 'token_uri': 'https://oauth2.googleapis.com/token',
                        'redirect_uris': [redirect_uri]}}

    @classmethod
    def auth_url(cls, state: str, redirect_uri: str, hint: Optional[str] = None) -> str:
        flow = Flow.from_client_config(cls._config(redirect_uri), scopes=cls.SCOPES, redirect_uri=redirect_uri)
        extra = {'login_hint': hint} if hint else {}
        # select_account: the owner picks which Google account (it used to reuse the signed-in one, so a second account
        # could not be added); consent: a refresh token every time
        url, _ = flow.authorization_url(access_type='offline', include_granted_scopes='true', prompt='select_account consent', state=state, **extra)
        return url

    @classmethod
    def exchange(cls, code: str, redirect_uri: str) -> tuple[str, dict]:
        # An account that already granted this app other permissions (0aw325171: Gmail) gets them back with the calendar ones
        # (include_granted_scopes), and oauthlib refused the token as "Scope has changed" after a successful consent
        # (2026-09-25). More than asked is fine; what matters is that the calendar permissions are among them.
        os.environ.setdefault('OAUTHLIB_RELAX_TOKEN_SCOPE', '1')
        flow = Flow.from_client_config(cls._config(redirect_uri), scopes=cls.SCOPES, redirect_uri=redirect_uri)
        flow.fetch_token(code=code)
        creds = flow.credentials
        granted = set(creds.scopes or flow.oauth2session.token.get('scope', []) or [])
        missing = [s for s in cls.SCOPES if granted and s not in granted]
        if missing:
            raise ValueError('カレンダーの権限が許可されていません（許可の画面でカレンダーの項目にチェックを入れて、もう一度つなぐ）: ' + ', '.join(missing))
        address = build('calendar', 'v3', credentials=creds).calendarList().get(calendarId='primary').execute().get('id', '')
        return address, {'token': creds.token, 'refresh_token': creds.refresh_token, 'token_uri': creds.token_uri,
                         'client_id': creds.client_id, 'client_secret': creds.client_secret,
                         'scopes': list(creds.scopes) if creds.scopes else cls.SCOPES}

    def __init__(self, account: dict, token: dict, save_token):
        self.account = account
        creds = Credentials(token=token['token'], refresh_token=token.get('refresh_token'),
                            token_uri=token.get('token_uri', 'https://oauth2.googleapis.com/token'),
                            client_id=token.get('client_id'), client_secret=token.get('client_secret'),
                            scopes=token.get('scopes', self.SCOPES))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            save_token({**token, 'token': creds.token})
        self.api = build('calendar', 'v3', credentials=creds, cache_discovery=False)
        self._calendars = None

    def calendars(self) -> list[dict]:
        if self._calendars is None:
            items = self.api.calendarList().list(maxResults=50).execute().get('items', [])
            self._calendars = [{'id': c['id'], 'name': c.get('summaryOverride') or c.get('summary') or c['id'], 'primary': bool(c.get('primary'))}
                               for c in items if c.get('selected', True)]
        return self._calendars

    def events(self, start: datetime, end: datetime, limit: int = 50) -> list[dict]:
        out = []
        for calendar in self.calendars()[:15]:
            items = self.api.events().list(calendarId=calendar['id'], timeMin=start.isoformat(), timeMax=end.isoformat(),
                                           maxResults=limit, singleEvents=True, orderBy='startTime').execute().get('items', [])
            for item in items:
                s, e = item.get('start', {}), item.get('end', {})
                out.append({'id': item['id'], 'calendar_id': calendar['id'], 'calendar': calendar['name'],
                            'title': item.get('summary', '(タイトルなし)'), 'start': s.get('dateTime', s.get('date', '')),
                            'end': e.get('dateTime', e.get('date', '')), 'location': item.get('location', ''),
                            'description': item.get('description', ''),
                            'reminders': [o.get('minutes') for o in (item.get('reminders') or {}).get('overrides', [])]})
        return out

    @staticmethod
    def _body(fields: dict) -> dict:
        body = {}
        if fields.get('title') is not None: body['summary'] = fields['title']
        if fields.get('start'): body['start'] = _when(fields['start'])
        if fields.get('end'): body['end'] = _when(fields['end'])
        if fields.get('description') is not None: body['description'] = fields['description']
        if fields.get('location') is not None: body['location'] = fields['location']
        if fields.get('reminders') is not None:
            body['reminders'] = {'useDefault': False, 'overrides': [{'method': 'popup', 'minutes': int(m)} for m in fields['reminders']]}
        return body

    def create(self, calendar_id: Optional[str], fields: dict) -> dict:
        made = self.api.events().insert(calendarId=calendar_id or 'primary', body=self._body(fields)).execute()
        return self._short(made, calendar_id or 'primary')

    def update(self, calendar_id: str, event_id: str, fields: dict) -> dict:
        made = self.api.events().patch(calendarId=calendar_id, eventId=event_id, body=self._body(fields)).execute()
        return self._short(made, calendar_id)

    def delete(self, calendar_id: str, event_id: str) -> None:
        self.api.events().delete(calendarId=calendar_id, eventId=event_id).execute()

    def get(self, calendar_id: str, event_id: str) -> Optional[dict]:
        try:
            item = self.api.events().get(calendarId=calendar_id, eventId=event_id).execute()
        except Exception:
            return None
        return self._short(item, calendar_id)

    def _short(self, item: dict, calendar_id: str) -> dict:
        s = item.get('start', {})
        return {'id': item['id'], 'calendar_id': calendar_id, 'account': self.account['account'], 'title': item.get('summary', ''),
                'start': s.get('dateTime', s.get('date', '')), 'description': item.get('description', ''),
                'link': item.get('htmlLink', '')}


PROVIDERS = {'google': GoogleCalendar}


def provider_class(name: str):
    if name not in PROVIDERS:
        raise ValueError(f'{name} のカレンダーにはまだ対応していません（対応: {", ".join(PROVIDERS)}）')
    return PROVIDERS[name]

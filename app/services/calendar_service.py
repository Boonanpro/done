"""
Google Calendar Service - OAuth + 予定の読み書き
"""
import json
import logging
from typing import Optional, List, Tuple
from datetime import datetime, timezone, timedelta

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from app.config import settings
from app.services.supabase_client import get_supabase_client
from app.services.encryption import encrypt_data, decrypt_data

logger = logging.getLogger(__name__)

CALENDAR_SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
]

CALENDAR_REDIRECT_URI = "http://localhost:8000/api/v1/calendar/callback"


class CalendarService:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.client_config = {
            "web": {
                "client_id": settings.gmail_client_id,
                "client_secret": settings.gmail_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [CALENDAR_REDIRECT_URI],
            }
        }

    def get_auth_url(self, user_id: str) -> str:
        """OAuth2認証URLを生成"""
        flow = Flow.from_client_config(
            self.client_config,
            scopes=CALENDAR_SCOPES,
            redirect_uri=CALENDAR_REDIRECT_URI,
        )
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent',
            state=user_id,
        )
        return auth_url

    async def handle_callback(self, code: str, user_id: str) -> Tuple[bool, str, Optional[str]]:
        """OAuth2コールバック処理"""
        try:
            flow = Flow.from_client_config(
                self.client_config,
                scopes=CALENDAR_SCOPES,
                redirect_uri=CALENDAR_REDIRECT_URI,
            )
            flow.fetch_token(code=code)
            credentials = flow.credentials

            # メールアドレス取得
            service = build('calendar', 'v3', credentials=credentials)
            cal_list = service.calendarList().get(calendarId='primary').execute()
            email = cal_list.get('id', '')

            # トークン暗号化保存
            token_data = {
                'token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'token_uri': credentials.token_uri,
                'client_id': credentials.client_id,
                'client_secret': credentials.client_secret,
                'scopes': list(credentials.scopes) if credentials.scopes else CALENDAR_SCOPES,
            }
            encrypted_token = encrypt_data(json.dumps(token_data))

            existing = self.supabase.table("calendar_connections").select("id").eq("user_id", user_id).execute()
            if existing.data:
                self.supabase.table("calendar_connections").update({
                    "email": email,
                    "encrypted_token": encrypted_token,
                    "is_active": True,
                }).eq("user_id", user_id).execute()
            else:
                self.supabase.table("calendar_connections").insert({
                    "user_id": user_id,
                    "email": email,
                    "encrypted_token": encrypted_token,
                    "is_active": True,
                }).execute()

            logger.info("Calendar connected for user %s: %s", user_id, email)
            return True, "Google Calendar connected", email

        except Exception as e:
            logger.error("Calendar OAuth failed: %s", e)
            return False, str(e), None

    def _get_credentials(self, user_id: str) -> Optional[Credentials]:
        """保存済みトークンからCredentialsを復元"""
        result = self.supabase.table("calendar_connections").select("encrypted_token, is_active").eq("user_id", user_id).execute()
        if not result.data or not result.data[0].get("is_active"):
            return None

        try:
            token_data = json.loads(decrypt_data(result.data[0]["encrypted_token"]))
            creds = Credentials(
                token=token_data['token'],
                refresh_token=token_data.get('refresh_token'),
                token_uri=token_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
                client_id=token_data.get('client_id'),
                client_secret=token_data.get('client_secret'),
                scopes=token_data.get('scopes', CALENDAR_SCOPES),
            )
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                # 更新されたトークンを保存
                token_data['token'] = creds.token
                encrypted = encrypt_data(json.dumps(token_data))
                self.supabase.table("calendar_connections").update({
                    "encrypted_token": encrypted,
                }).eq("user_id", user_id).execute()
            return creds
        except Exception as e:
            logger.error("Failed to load calendar credentials: %s", e)
            return None

    async def get_status(self, user_id: str) -> dict:
        """カレンダー連携状態"""
        result = self.supabase.table("calendar_connections").select("email, is_active").eq("user_id", user_id).execute()
        if not result.data:
            return {"connected": False, "email": None}
        conn = result.data[0]
        return {"connected": conn.get("is_active", False), "email": conn.get("email")}

    async def disconnect(self, user_id: str) -> bool:
        """連携解除"""
        self.supabase.table("calendar_connections").update({"is_active": False}).eq("user_id", user_id).execute()
        return True

    # ==================== カレンダー操作 ====================

    def get_events(self, user_id: str, days: int = 7, max_results: int = 20) -> List[dict]:
        """今後N日間の予定を取得（連携アカウントが見ている全カレンダー。各予定に calendar 名が付く）"""
        return self.get_events_with_source(user_id, days, max_results)['events']

    def get_events_with_source(self, user_id: str, days: int = 7, max_results: int = 20) -> dict:
        """予定と、その出どころ（どのアカウントの、どのカレンダーを見たか）。
        「何を見て言った」に答えられない読み取りは読み取りではない: 読む道具は必ず source を返す。"""
        creds = self._get_credentials(user_id)
        if not creds:
            return {'events': [{"error": "カレンダー未連携。設定画面から連携してください。"}], 'source': None}

        service = build('calendar', 'v3', credentials=creds)
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=days)
        calendars = [c for c in service.calendarList().list(maxResults=20).execute().get('items', []) if c.get('selected', True)]
        account = next((c['id'] for c in calendars if c.get('primary')), '')

        events = []
        for calendar in calendars[:10]:
            result = service.events().list(
                calendarId=calendar['id'],
                timeMin=now.isoformat(),
                timeMax=time_max.isoformat(),
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime',
            ).execute()
            for item in result.get('items', []):
                start = item.get('start', {})
                end = item.get('end', {})
                events.append({
                    'id': item['id'],
                    'title': item.get('summary', '(タイトルなし)'),
                    'start': start.get('dateTime', start.get('date', '')),
                    'end': end.get('dateTime', end.get('date', '')),
                    'location': item.get('location', ''),
                    'description': item.get('description', ''),
                    'calendar': calendar.get('summaryOverride') or calendar.get('summary') or calendar['id'],
                })
        events.sort(key=lambda e: e['start'])
        return {'events': events[:max_results],
                'source': {'account': account, 'calendars': [c.get('summaryOverride') or c.get('summary') or c['id'] for c in calendars[:10]]}}

    def create_event(self, user_id: str, title: str, start: str, end: str,
                     description: str = "", location: str = "") -> dict:
        """予定を作成"""
        creds = self._get_credentials(user_id)
        if not creds:
            return {"error": "カレンダー未連携。設定画面から連携してください。"}

        service = build('calendar', 'v3', credentials=creds)

        # 日付のみか日時か判定
        is_all_day = len(start) <= 10
        event_body = {
            'summary': title,
            'start': {'date': start} if is_all_day else {'dateTime': start, 'timeZone': 'Asia/Tokyo'},
            'end': {'date': end} if is_all_day else {'dateTime': end, 'timeZone': 'Asia/Tokyo'},
        }
        if description:
            event_body['description'] = description
        if location:
            event_body['location'] = location

        created = service.events().insert(calendarId='primary', body=event_body).execute()
        return {
            'id': created['id'],
            'title': created.get('summary', ''),
            'start': created['start'].get('dateTime', created['start'].get('date', '')),
            'link': created.get('htmlLink', ''),
        }

    def find_free_slots(self, user_id: str, days: int = 7) -> List[dict]:
        """今後N日間の空き時間を取得（9:00-18:00の営業時間内）"""
        events = self.get_events(user_id, days=days)
        if events and isinstance(events[0], dict) and "error" in events[0]:
            return events

        # 日ごとの空き時間を計算
        now = datetime.now(timezone(timedelta(hours=9)))  # JST
        free_slots = []

        for day_offset in range(days):
            day = now.date() + timedelta(days=day_offset)
            day_start = datetime(day.year, day.month, day.day, 9, 0, tzinfo=timezone(timedelta(hours=9)))
            day_end = datetime(day.year, day.month, day.day, 18, 0, tzinfo=timezone(timedelta(hours=9)))

            if day_start < now:
                day_start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                if day_start >= day_end:
                    continue

            # この日の予定を抽出
            day_events = []
            for ev in events:
                if isinstance(ev, dict) and 'start' in ev:
                    try:
                        ev_start = datetime.fromisoformat(ev['start'].replace('Z', '+00:00'))
                        ev_end = datetime.fromisoformat(ev['end'].replace('Z', '+00:00'))
                        if ev_start.date() == day:
                            day_events.append((ev_start, ev_end))
                    except (ValueError, KeyError):
                        pass

            day_events.sort()

            # 空き時間を計算
            cursor = day_start
            for ev_start, ev_end in day_events:
                if cursor < ev_start:
                    free_slots.append({
                        'date': day.isoformat(),
                        'start': cursor.strftime('%H:%M'),
                        'end': ev_start.strftime('%H:%M'),
                    })
                if ev_end > cursor:
                    cursor = ev_end
            if cursor < day_end:
                free_slots.append({
                    'date': day.isoformat(),
                    'start': cursor.strftime('%H:%M'),
                    'end': day_end.strftime('%H:%M'),
                })

        return free_slots


def get_calendar_service() -> CalendarService:
    return CalendarService()

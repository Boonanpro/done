"""Current outbound card state, read only after room access is checked."""
import asyncio
from datetime import datetime, timedelta, timezone
from app.services.outbound_message_service import OutboundMessageService


async def outbound_cards(room_id):
    try:
        rows = await asyncio.to_thread(OutboundMessageService().list_for_room, room_id, limit=20)
        cards = []
        for row in rows:
            data = row.get('action_data') or {}
            card = {**{k: row.get(k) for k in ('id', 'status', 'created_at', 'updated_at', 'responded_at')},
                          **{k: data.get(k) for k in ('channel', 'to_name', 'subject', 'sent_at', 'sent_by', 'error')},
                          'body': (row.get('content') or '')[:1400]}
            for key in ('created_at', 'updated_at', 'responded_at', 'sent_at'):
                if card.get(key):
                    at = datetime.fromisoformat(card[key].replace('Z', '+00:00'))
                    if at.tzinfo is not None:
                        card[key] = at.astimezone(timezone(timedelta(hours=9))).isoformat()
            cards.append(card)
        return {'cards': cards, 'limit': 20, 'timezone': 'Asia/Tokyo'}
    except Exception:
        return {'error': 'outbound_card_state_unavailable'}

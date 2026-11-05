"""Authorized telephone operations. Never call without the owner's explicit request.

owner --room UUID --approved: call the owner's saved phone, at most 10 minutes.
external --room UUID --to E164 --purpose-file FILE --approved: scoped inquiry;
  only purpose-file content is shared, with no owner tools or room history.
status KEY: read actual Twilio state and local conversation outcome, no redial.
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from app.config import settings
from app.services import telephone as T


async def main(args):
    async with httpx.AsyncClient(timeout=25) as client:
        base = 'https://api.twilio.com/2010-04-01/Accounts/' + settings.TWILIO_ACCOUNT_SID
        auth = (settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        if args.action == 'status':
            grant = T.read(args.key)
            r = await client.get(base + '/Calls/' + grant['call_sid'] + '.json', auth=auth)
            r.raise_for_status()
            data = r.json()
            print(json.dumps({'key': args.key, 'status': data['status'], 'duration': data.get('duration'),
                'result': grant.get('result')}, ensure_ascii=False))
            return
        if not args.approved:
            raise ValueError('Explicit owner authorization is required')
        # Public readiness must match this implementation, not any HTTP 200 page.
        r = await client.get(T.origin() + '/api/v1/voice/telephone/ready')
        r.raise_for_status()
        if r.json().get('version') != T.VERSION:
            raise RuntimeError('The public telephone endpoint is not ready')
        from app.services.owner import resolve_owner_user_id
        user = resolve_owner_user_id()
        if args.action == 'owner':
            from app.services.personal_info_service import get_personal_info_service
            info = await get_personal_info_service().get(user, 'phone')
            number = str((info or {}).get('value') or '')
            purpose = '本人が希望した電話の動作確認。自然に会話し、切ってと言われたら終了する。'
        else:
            number = args.to
            purpose = Path(args.purpose_file).read_text()
        import re
        if not re.fullmatch(r'\+[1-9][0-9]{7,14}', number or ''):
            raise ValueError('A valid E.164 destination is required')
        key = T.secrets.token_hex(24)
        grant = {'user_id': user, 'room_id': args.room, 'peer': args.action,
            'purpose': purpose, 'expires': time.time()+180, 'max_seconds': args.max_seconds}
        # Prepare room context and catch configuration/access errors before ringing.
        await T.config_for(grant)
        T.save(key, grant)
        # No automatic retry: a timeout may mean the call was already placed.
        r = await client.post(base + '/Calls.json', auth=auth, data={
            'To': number, 'From': settings.TWILIO_PHONE_NUMBER, 'Twiml': T.twiml(key),
            'Timeout': '30', 'TimeLimit': str(args.max_seconds)})
        if r.status_code >= 400:
            data = r.json()
            print(json.dumps({'key': key, 'failed': True, 'http': r.status_code, 'code': data.get('code')}))
            return
        data = r.json()
        grant['call_sid'] = data['sid']
        T.save(key, grant)
        print(json.dumps({'key': key, 'status': data['status']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['owner', 'external', 'status'])
    parser.add_argument('--room')
    parser.add_argument('--key')
    parser.add_argument('--to')
    parser.add_argument('--purpose-file')
    parser.add_argument('--approved', action='store_true')
    parser.add_argument('--max-seconds', type=int, default=600, choices=range(30, 1801))
    asyncio.run(main(parser.parse_args()))

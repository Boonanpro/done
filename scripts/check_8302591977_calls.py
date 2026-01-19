"""
+18302591977への着信履歴を確認
"""
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

account_sid = os.getenv('TWILIO_ACCOUNT_SID')
auth_token = os.getenv('TWILIO_AUTH_TOKEN')

client = Client(account_sid, auth_token)

PHONE_NUMBER = "+18302591977"

print("=" * 70)
print(f"Recent calls to {PHONE_NUMBER}")
print("=" * 70)
print()

# 過去24時間の着信を取得
date_after = datetime.utcnow() - timedelta(hours=24)

calls = client.calls.list(
    to=PHONE_NUMBER,
    start_time_after=date_after,
    limit=20
)

if not calls:
    print("No incoming calls found in the last 24 hours.")
else:
    print(f"Found {len(calls)} call(s):")
    print()
    
    for call in calls:
        print(f"From: {call.from_}")
        print(f"  Time: {call.start_time}")
        print(f"  Status: {call.status}")
        print(f"  Duration: {call.duration}s")
        print(f"  Direction: {call.direction}")
        print()

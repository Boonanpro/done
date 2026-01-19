"""
最新の録音をチェックしてダウンロードURLを表示
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
print(f"Latest recordings for {PHONE_NUMBER}")
print("=" * 70)
print()

# 過去1時間の着信を取得
date_after = datetime.utcnow() - timedelta(hours=1)

calls = client.calls.list(
    to=PHONE_NUMBER,
    start_time_after=date_after,
    limit=10
)

if not calls:
    print("No calls found in the last hour.")
    print()
    print("Try extending the search range:")
    print("  Edit date_after in this script to search further back")
else:
    print(f"Found {len(calls)} call(s):")
    print()

    for call in calls:
        print(f"Call from: {call.from_}")
        print(f"  Time: {call.start_time}")
        print(f"  Status: {call.status}")
        print(f"  Duration: {call.duration}s")
        print(f"  SID: {call.sid}")

        # 録音を取得
        recordings = client.recordings.list(call_sid=call.sid)

        if recordings:
            for recording in recordings:
                recording_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Recordings/{recording.sid}.mp3"
                print(f"  Recording SID: {recording.sid}")
                print(f"  Recording duration: {recording.duration}s")
                print(f"  Recording URL: {recording_url}")
                print()
                print("  To transcribe:")
                print(f"    python scripts/transcribe_recording.py {recording.sid}")
                print()
        else:
            print("  [WARN] No recording found")
            print()

print()
print("=" * 70)
print("Next steps:")
print("=" * 70)
print()
print("1. Download recording using the URL above (with Twilio credentials)")
print("2. Or use transcribe_recording.py to automatically transcribe")
print("3. Extract OTP code from the transcription")

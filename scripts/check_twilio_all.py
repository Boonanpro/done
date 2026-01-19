"""
Twilio 全着信・SMS履歴を確認
"""
import os
import sys
sys.path.insert(0, "D:\\done")

from dotenv import load_dotenv
load_dotenv("D:\\done\\.env")

from twilio.rest import Client

def main():
    account_sid = os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = os.getenv('TWILIO_AUTH_TOKEN')
    
    client = Client(account_sid, auth_token)
    
    print("=" * 60)
    print("ALL Recent Calls (any direction, last 20)")
    print("=" * 60)
    
    try:
        calls = client.calls.list(limit=20)
        if calls:
            for call in calls:
                print(f"{call.start_time}")
                print(f"  From: {call.from_formatted} -> To: {call.to_formatted}")
                print(f"  Status: {call.status} | Duration: {call.duration}s")
                print(f"  Direction: {call.direction}")
                print()
        else:
            print("No calls found")
    except Exception as e:
        print(f"Error: {e}")
    
    print("=" * 60)
    print("ALL Recent SMS (any direction, last 20)")
    print("=" * 60)
    
    try:
        messages = client.messages.list(limit=20)
        if messages:
            for msg in messages:
                print(f"{msg.date_sent}")
                print(f"  From: {msg.from_} -> To: {msg.to}")
                print(f"  Direction: {msg.direction}")
                print(f"  Body: {msg.body}")
                print()
        else:
            print("No SMS found")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()


"""
Twilio設定状態と着信履歴を確認
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
    phone_number = os.getenv('TWILIO_PHONE_NUMBER')
    
    print("=" * 50)
    print("Twilio Status Check")
    print("=" * 50)
    
    print(f"\nPhone Number: {phone_number}")
    print(f"Account SID: {account_sid[:10]}..." if account_sid else "Account SID: Not set")
    
    if not account_sid or not auth_token:
        print("\nERROR: Twilio credentials not found in .env")
        return
    
    client = Client(account_sid, auth_token)
    
    # 電話番号の設定を確認
    print("\n" + "-" * 50)
    print("Phone Number Configuration:")
    print("-" * 50)
    
    try:
        incoming_numbers = client.incoming_phone_numbers.list(phone_number=phone_number)
        if incoming_numbers:
            num = incoming_numbers[0]
            print(f"  Friendly Name: {num.friendly_name}")
            print(f"  Phone Number: {num.phone_number}")
            print(f"  Voice URL: {num.voice_url or 'Not set'}")
            print(f"  Voice Method: {num.voice_method or 'Not set'}")
            print(f"  SMS URL: {num.sms_url or 'Not set'}")
            print(f"  SMS Method: {num.sms_method or 'Not set'}")
        else:
            print(f"  Phone number {phone_number} not found in account")
    except Exception as e:
        print(f"  Error: {e}")
    
    # 最近の着信履歴を確認
    print("\n" + "-" * 50)
    print("Recent Incoming Calls (last 10):")
    print("-" * 50)
    
    try:
        calls = client.calls.list(to=phone_number, limit=10)
        if calls:
            for call in calls:
                print(f"  {call.start_time} | From: {call.from_formatted} | Status: {call.status} | Duration: {call.duration}s")
        else:
            print("  No incoming calls found")
    except Exception as e:
        print(f"  Error: {e}")
    
    # 最近のSMS履歴を確認
    print("\n" + "-" * 50)
    print("Recent Incoming SMS (last 10):")
    print("-" * 50)
    
    try:
        messages = client.messages.list(to=phone_number, limit=10)
        if messages:
            for msg in messages:
                print(f"  {msg.date_sent} | From: {msg.from_} | Body: {msg.body[:50]}...")
        else:
            print("  No incoming SMS found")
    except Exception as e:
        print(f"  Error: {e}")
    
    print("\n" + "=" * 50)


if __name__ == "__main__":
    main()


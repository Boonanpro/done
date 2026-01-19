"""
Twilio番号に届いた最新のSMSからOTPコードを抽出
"""
import os
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

account_sid = os.getenv('TWILIO_ACCOUNT_SID')
auth_token = os.getenv('TWILIO_AUTH_TOKEN')

client = Client(account_sid, auth_token)

PHONE_NUMBER = "+18302591977"

def get_latest_sms_otp(minutes=5):
    """
    指定した分数以内に受信した最新のSMSからOTPを抽出
    
    Args:
        minutes: 何分前までのSMSを確認するか
        
    Returns:
        str: OTPコード、見つからなければNone
    """
    print(f"Checking SMS received in last {minutes} minutes...")
    print(f"Phone number: {PHONE_NUMBER}")
    print()
    
    # 指定時間以降のSMSを取得
    date_sent_after = datetime.utcnow() - timedelta(minutes=minutes)
    
    messages = client.messages.list(
        to=PHONE_NUMBER,
        date_sent_after=date_sent_after,
        limit=10
    )
    
    if not messages:
        print("No SMS found in the specified time range.")
        return None
    
    print(f"Found {len(messages)} message(s):")
    print()
    
    for msg in messages:
        print(f"From: {msg.from_}")
        print(f"Received: {msg.date_sent}")
        print(f"Body: {msg.body}")
        
        # OTPパターンを探す（6桁の数字が一般的）
        otp_patterns = [
            r'\b(\d{6})\b',  # 6桁
            r'\b(\d{4})\b',  # 4桁
            r'\b(\d{8})\b',  # 8桁
        ]
        
        for pattern in otp_patterns:
            match = re.search(pattern, msg.body)
            if match:
                otp = match.group(1)
                print(f"  -> OTP detected: {otp}")
                print()
                return otp
        
        print("  -> No OTP pattern found")
        print()
    
    return None

if __name__ == "__main__":
    otp = get_latest_sms_otp(minutes=10)
    
    if otp:
        print("=" * 70)
        print(f"OTP Code: {otp}")
        print("=" * 70)
    else:
        print("=" * 70)
        print("No OTP found")
        print("=" * 70)

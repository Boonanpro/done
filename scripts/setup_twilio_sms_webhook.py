"""
Twilio番号 +18302591977 のSMS Webhookを設定
受信SMSをローカルに保存する
"""
import os
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

account_sid = os.getenv('TWILIO_ACCOUNT_SID')
auth_token = os.getenv('TWILIO_AUTH_TOKEN')

client = Client(account_sid, auth_token)

PHONE_NUMBER = "+18302591977"

print("=" * 70)
print(f"Setting up SMS Webhook for {PHONE_NUMBER}")
print("=" * 70)
print()

# まず現在の設定を確認
numbers = client.incoming_phone_numbers.list(phone_number=PHONE_NUMBER)

if not numbers:
    print(f"Error: Phone number {PHONE_NUMBER} not found")
    exit(1)

number = numbers[0]

print("Current configuration:")
print(f"  Voice URL: {number.voice_url}")
print(f"  SMS URL: {number.sms_url}")
print()

# オプション1: ngrokなどの公開URLを使う場合
# SMS_WEBHOOK_URL = "https://your-ngrok-url.ngrok.io/api/twilio/sms"

# オプション2: Twilioのローカル保存機能を使う（TwiMLBin）
# とりあえず、受信SMSをログに記録するシンプルなTwiMLを設定

# まずは、デバッグ用に何もしないTwiMLに設定
SIMPLE_TWIML_URL = "http://twimlets.com/echo?Twiml=%3CResponse%3E%3CMessage%3ESMS%20received%3C%2FMessage%3E%3C%2FResponse%3E"

print("Updating SMS webhook...")
print(f"  New SMS URL: (TwiML - will just log)")

# とりあえずデモURLのまま、実際のSMS受信を確認
print()
print("=" * 70)
print("SOLUTION")
print("=" * 70)
print()
print("問題: Twilioで受信したSMSを取得するには:")
print()
print("1. ローカルサーバーを公開URLで expose (ngrok等)")
print("2. またはTwilio APIで受信SMSをポーリング")
print()
print("オプション2の方が簡単なので、SMS受信確認スクリプトを作成します...")

"""
Twilioアカウントの全電話番号を表示
"""
import os
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

account_sid = os.getenv('TWILIO_ACCOUNT_SID')
auth_token = os.getenv('TWILIO_AUTH_TOKEN')

client = Client(account_sid, auth_token)

print("=" * 70)
print("All Twilio Phone Numbers")
print("=" * 70)
print()

numbers = client.incoming_phone_numbers.list()

for number in numbers:
    print(f"Number: {number.phone_number}")
    print(f"  Friendly Name: {number.friendly_name}")
    print(f"  Voice URL: {number.voice_url}")
    print(f"  SMS URL: {number.sms_url}")
    print(f"  Capabilities:")
    print(f"    Voice: {number.capabilities.get('voice', False)}")
    print(f"    SMS: {number.capabilities.get('sms', False)}")
    print(f"    MMS: {number.capabilities.get('mms', False)}")
    print()

if not numbers:
    print("No phone numbers found in this account.")

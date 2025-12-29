# -*- coding: utf-8 -*-
"""Check Twilio Verified Numbers"""
import os
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

c = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))

print("=== Verified Caller IDs ===")
try:
    caller_ids = c.outgoing_caller_ids.list()
    if not caller_ids:
        print("No verified caller IDs found!")
    for cid in caller_ids:
        print(f"Phone: {cid.phone_number}")
        print(f"Friendly Name: {cid.friendly_name}")
        print(f"SID: {cid.sid}")
        print("---")
except Exception as e:
    print(f"Error: {e}")

print("\n=== Account Info ===")
account = c.api.accounts(c.account_sid).fetch()
print(f"Account SID: {account.sid}")
print(f"Account Status: {account.status}")
print(f"Account Type: {account.type}")




# -*- coding: utf-8 -*-
"""Check Twilio Verified Numbers"""
from twilio.rest import Client

c = Client('AC8d0e1a1e20e2c3925a5077c926735290', '451e4ae0bf1e7a2a6d11d7e8ade9c95c')

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



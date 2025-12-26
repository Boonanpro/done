# -*- coding: utf-8 -*-
"""Check Twilio Account Status and Permissions"""
from twilio.rest import Client

account_sid = 'AC8d0e1a1e20e2c3925a5077c926735290'
auth_token = '451e4ae0bf1e7a2a6d11d7e8ade9c95c'

c = Client(account_sid, auth_token)

# Account balance
print("=== Account Balance ===")
try:
    balance = c.api.accounts(account_sid).balance.fetch()
    print(f"Balance: {balance.balance} {balance.currency}")
except Exception as e:
    print(f"Error: {e}")

# Account details
print("\n=== Account Details ===")
account = c.api.accounts(account_sid).fetch()
print(f"Status: {account.status}")
print(f"Type: {account.type}")
print(f"Friendly Name: {account.friendly_name}")

# Phone number capabilities
print("\n=== Phone Number Details ===")
try:
    numbers = c.incoming_phone_numbers.list()
    for num in numbers:
        print(f"Number: {num.phone_number}")
        print(f"Friendly Name: {num.friendly_name}")
        print(f"Voice URL: {num.voice_url}")
        print(f"Voice Method: {num.voice_method}")
        print(f"Capabilities: {num.capabilities}")
except Exception as e:
    print(f"Error: {e}")

# Check recent call errors
print("\n=== Recent Calls with Errors ===")
calls = c.calls.list(limit=5)
for call in calls:
    print(f"SID: {call.sid}")
    print(f"  Status: {call.status}")
    print(f"  Duration: {call.duration}s")
    print(f"  To: {call.to}")
    # Check for warnings/errors
    try:
        # Fetch full call details
        call_detail = c.calls(call.sid).fetch()
        if hasattr(call_detail, 'subresource_uris'):
            print(f"  Subresources: {call_detail.subresource_uris}")
    except:
        pass
    print()




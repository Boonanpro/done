# -*- coding: utf-8 -*-
"""Create TwiML Bin and Test Call"""
import os
from dotenv import load_dotenv
import requests
from twilio.rest import Client

load_dotenv()

account_sid = os.getenv('TWILIO_ACCOUNT_SID')
auth_token = os.getenv('TWILIO_AUTH_TOKEN')

# TwiML content
twiml_content = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say language="en-US">Hello. This is Dan, your AI assistant. The voice system is working correctly.</Say>
    <Pause length="1"/>
    <Say language="en-US">Goodbye.</Say>
    <Hangup/>
</Response>'''

# Create TwiML Bin
print("Creating TwiML Bin...")
url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls.json"

# Use a public TwiML hosting service instead
# Try using Twilio's demo TwiML first
demo_twiml_url = "http://demo.twilio.com/docs/voice.xml"

print(f"Using demo TwiML URL: {demo_twiml_url}")
print()

# Make call with URL instead of twiml parameter
c = Client(account_sid, auth_token)
call = c.calls.create(
    to='+817083524060',
    from_='+16316145862',
    url=demo_twiml_url  # Use URL instead of twiml
)
print(f'Call SID: {call.sid}')
print(f'Status: {call.status}')




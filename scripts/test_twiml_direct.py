# -*- coding: utf-8 -*-
"""Twilio TwiML Direct Test - using twiml parameter"""
import os
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

load_dotenv()

# Create TwiML
response = VoiceResponse()
response.say('Hello. This is Dan, your AI assistant. The voice system is working.', language='en-US')
response.pause(length=1)
response.say('Goodbye.', language='en-US')
response.hangup()

twiml_str = str(response)
print('TwiML:')
print(twiml_str)
print()

# Make call with TWIML parameter (not URL)
c = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))

print("Making call with twiml parameter...")
call = c.calls.create(
    to='+817083524060',
    from_='+16316145862',
    twiml=twiml_str  # Using TWIML parameter directly!
)
print(f'Call SID: {call.sid}')
print(f'Status: {call.status}')




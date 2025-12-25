# -*- coding: utf-8 -*-
"""Twilio TwiML Direct Test - using twiml parameter"""
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

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
c = Client('AC8d0e1a1e20e2c3925a5077c926735290', '451e4ae0bf1e7a2a6d11d7e8ade9c95c')

print("Making call with twiml parameter...")
call = c.calls.create(
    to='+817083524060',
    from_='+16316145862',
    twiml=twiml_str  # Using TWIML parameter directly!
)
print(f'Call SID: {call.sid}')
print(f'Status: {call.status}')


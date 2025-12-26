# -*- coding: utf-8 -*-
"""Twilio TwiML Test - English"""
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

# Create TwiML with English message
response = VoiceResponse()
response.say('Hello. This is a test call from Dan, your AI assistant.', language='en-US')
response.pause(length=1)
response.say('The voice system is working correctly. Goodbye.', language='en-US')
response.hangup()

twiml_str = str(response)
print('TwiML:')
print(twiml_str)
print()

# Make call
c = Client('AC8d0e1a1e20e2c3925a5077c926735290', '451e4ae0bf1e7a2a6d11d7e8ade9c95c')
call = c.calls.create(
    to='+817083524060',
    from_='+16316145862',
    twiml=twiml_str
)
print(f'Call SID: {call.sid}')
print(f'Status: {call.status}')




# -*- coding: utf-8 -*-
"""Twilio TwiML Test - English"""
import os
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

load_dotenv()

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
c = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
call = c.calls.create(
    to='+817083524060',
    from_='+16316145862',
    twiml=twiml_str
)
print(f'Call SID: {call.sid}')
print(f'Status: {call.status}')




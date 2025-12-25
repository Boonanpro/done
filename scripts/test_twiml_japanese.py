# -*- coding: utf-8 -*-
"""Twilio TwiML Test - Japanese"""
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

# Create TwiML with Japanese message
response = VoiceResponse()
response.say('こんにちは。AIアシスタントのダンです。音声システムが正常に動作しています。', language='ja-JP')
response.pause(length=1)
response.say('ご用件をお伺いします。何かお手伝いできることはありますか？', language='ja-JP')
response.pause(length=2)
response.say('テスト通話を終了します。さようなら。', language='ja-JP')
response.hangup()

twiml_str = str(response)
print('TwiML:')
print(twiml_str)
print()

# Make call
c = Client('AC8d0e1a1e20e2c3925a5077c926735290', '451e4ae0bf1e7a2a6d11d7e8ade9c95c')

print("Making call with Japanese TwiML...")
call = c.calls.create(
    to='+817083524060',
    from_='+16316145862',
    twiml=twiml_str
)
print(f'Call SID: {call.sid}')
print(f'Status: {call.status}')


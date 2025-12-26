# -*- coding: utf-8 -*-
"""Twilio TwiML テスト"""
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

# TwiMLを作成
response = VoiceResponse()
response.say('こんにちは。AIアシスタントのダンです。', language='ja-JP')
response.pause(length=1)
response.say('これはテスト通話です。音声機能が正常に動作しています。', language='ja-JP')
response.hangup()

twiml_str = str(response)
print('TwiML:')
print(twiml_str)
print()

# Twilioで発信
c = Client('AC8d0e1a1e20e2c3925a5077c926735290', '451e4ae0bf1e7a2a6d11d7e8ade9c95c')
call = c.calls.create(
    to='+817083524060',
    from_='+16316145862',
    twiml=twiml_str
)
print(f'Call SID: {call.sid}')
print(f'Status: {call.status}')




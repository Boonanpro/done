import asyncio
import websockets
import json
import sys

async def test():
    token = sys.argv[1]
    room_id = sys.argv[2]
    
    uri = 'ws://localhost:8000/api/v1/chat/ws/chat'
    print(f'Connecting to {uri}...')
    
    async with websockets.connect(uri) as ws:
        # 認証
        await ws.send(json.dumps({'type': 'auth', 'token': token}))
        print('Auth:', await ws.recv())
        
        # ルーム参加
        await ws.send(json.dumps({'type': 'join', 'room_id': room_id}))
        print('Join:', await ws.recv())
        
        # メッセージ送信
        print('Sending message...')
        await ws.send(json.dumps({'type': 'message', 'room_id': room_id, 'content': 'Hello WebSocket!'}))
        try:
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print('Message:', response)
        except asyncio.TimeoutError:
            print('Message: TIMEOUT (no response in 5s)')
        
        # Ping
        print('Sending ping...')
        await ws.send(json.dumps({'type': 'ping'}))
        try:
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print('Ping:', response)
        except asyncio.TimeoutError:
            print('Ping: TIMEOUT (no response in 5s)')
        
        print('\n✅ WebSocket test completed!')

asyncio.run(test())

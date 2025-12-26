# -*- coding: utf-8 -*-
"""Check Twilio Call Details"""
from twilio.rest import Client

c = Client('AC8d0e1a1e20e2c3925a5077c926735290', '451e4ae0bf1e7a2a6d11d7e8ade9c95c')

# Get latest call
calls = c.calls.list(limit=1)
for call in calls:
    print(f"=== Call Details ===")
    print(f"SID: {call.sid}")
    print(f"Status: {call.status}")
    print(f"Duration: {call.duration}s")
    print(f"Direction: {call.direction}")
    print(f"From: {call.from_formatted}")
    print(f"To: {call.to_formatted}")
    print(f"Start Time: {call.start_time}")
    print(f"End Time: {call.end_time}")
    print(f"Price: {call.price} {call.price_unit}")
    print(f"Answered By: {call.answered_by}")
    
    # Try to get events
    print("\n=== Call Events ===")
    try:
        events = c.calls(call.sid).events().list()
        for event in events:
            print(f"  {event.timestamp}: {event.name}")
    except Exception as e:
        print(f"  Could not fetch events: {e}")
    
    # Try to get notifications
    print("\n=== Call Notifications ===")
    try:
        notifications = c.calls(call.sid).notifications().list()
        if not notifications:
            print("  No notifications")
        for n in notifications:
            print(f"  Log: {n.log}")
            print(f"  Error Code: {n.error_code}")
            print(f"  Message: {n.message_text}")
    except Exception as e:
        print(f"  Could not fetch notifications: {e}")




# -*- coding: utf-8 -*-
"""Twilio Alerts Check"""
from twilio.rest import Client

c = Client('AC8d0e1a1e20e2c3925a5077c926735290', '451e4ae0bf1e7a2a6d11d7e8ade9c95c')

# Check latest alerts
try:
    alerts = c.monitor.alerts.list(limit=5)
    if not alerts:
        print("No alerts found")
    for a in alerts:
        print(f'Date: {a.date_created}')
        print(f'Error Code: {a.error_code}')
        print(f'Log Level: {a.log_level}')
        print(f'More Info: {a.more_info}')
        if a.alert_text:
            print(f'Alert Text: {a.alert_text[:300]}...')
        print('---')
except Exception as e:
    print(f"Error fetching alerts: {e}")

# Check latest call details
print("\n=== Latest Call Details ===")
calls = c.calls.list(limit=1)
for call in calls:
    print(f'SID: {call.sid}')
    print(f'Status: {call.status}')
    print(f'Duration: {call.duration}s')
    print(f'Start Time: {call.start_time}')
    print(f'End Time: {call.end_time}')
    print(f'Direction: {call.direction}')



# Telephone calls (2026-11-05)

Owner goal, before testing: Dan rings the owner's ordinary phone, hears and answers a natural conversation (including corrections while speaking), and actually disconnects when asked. A second unseen conversation must also preserve the changed fact and end. No call to Kyushu Card is authorized yet. Owner authorized a test call to himself and repairing telephone service.

Known bad: VOICE_WEBHOOK_BASE_URL points to an expired trycloudflare hostname (DNS fails). The legacy MediaStreamHandler waits for STT, reasoning and all TTS playback inside the receive loop, so cannot receive the peer while speaking. It also loses outbound purpose/context. A transport-only pass is not evidence of natural conversation.

Replacement: `telephone.py`, signed one-use outbound grants, permanent DAN_PUBLIC_ORIGIN, GPT-Live primary WebSocket in G.711 mu-law (matching Twilio). Input and output are independent. Twilio playback markers bound queued speech. Owner calls use the existing voice session/history/sideband. External calls receive only the explicitly prepared purpose, no private room history or owner tools. Caller identification is not owner authentication; incoming calls are not enabled by this change.

`telephone_call.py owner --room UUID --approved` requires authorization each operation. `external` additionally needs destination and purpose-file. No retries on an uncertain dial. `status --key KEY` reads the actual provider state and bridge result. A ten-minute provider limit also bounds abandoned calls. No automatic telephone retry or unsolicited call is scheduled.

Sources: https://developers.openai.com/api/docs/guides/voice-websockets ; https://www.twilio.com/docs/voice/media-streams/websocket-messages ; https://www.twilio.com/docs/usage/security .

## Verification before dialing

24 unit/transport/backend tests pass. Public new readiness endpoint initially returned 404 (saved `.tmp/telephone/before.json`). First real-model simulated telephone conversation correctly answered the changed color but only closed at the timeout: the initial checker incorrectly counted this as a pass; adding the bound rejects the saved 71.61-second case. Root cause: a primary Live WebSocket cannot be attached as if it were WebRTC. The existing voice backend now accepts a supplied event connection, so telephone audio and controls share one primary socket without duplicating the tool logic.

After the correction: color-3/color-4 and count-1/count-2 all preserve the changed color/quantity and close the Live session plus the simulated provider leg (2/2 each). Run folders: `.tmp/telephone/` in `telephone-realtime`; `result.json` includes the actual transcript, error and terminal conditions, `dan.ulaw` the returned audio. Synthetic peer, not yet an actual PSTN call or human naturalness verdict. Hangup elapsed values include speech generation and the full goodbye utterance, not just latency after the last word. Telephone playback, ringing and provider completion still require the owner's authorized call.

# Telephone calls (2026-11-05)

Owner goal, before testing: Dan rings the owner's ordinary phone, hears and answers a natural conversation (including corrections while speaking), and actually disconnects when asked. A second unseen conversation must also preserve the changed fact and end. No call to Kyushu Card is authorized yet. Owner authorized a test call to himself and repairing telephone service.

Known bad: VOICE_WEBHOOK_BASE_URL points to an expired trycloudflare hostname (DNS fails). The legacy MediaStreamHandler waits for STT, reasoning and all TTS playback inside the receive loop, so cannot receive the peer while speaking. It also loses outbound purpose/context. A transport-only pass is not evidence of natural conversation.

Replacement: `telephone.py`, signed one-use outbound grants, permanent DAN_PUBLIC_ORIGIN, GPT-Live primary WebSocket in G.711 mu-law (matching Twilio). Input and output are independent. Twilio playback markers bound queued speech. Owner calls use the existing voice session/history/sideband. External calls receive only the explicitly prepared purpose, no private room history or owner tools. Caller identification is not owner authentication; incoming calls are not enabled by this change.

`telephone_call.py owner --room UUID --approved` requires authorization each operation. `external` additionally needs destination and purpose-file. No retries on an uncertain dial. `status --key KEY` reads the actual provider state and bridge result. A ten-minute provider limit also bounds abandoned calls. No automatic telephone retry or unsolicited call is scheduled.

Sources: https://developers.openai.com/api/docs/guides/voice-websockets ; https://www.twilio.com/docs/voice/media-streams/websocket-messages ; https://www.twilio.com/docs/usage/security .

# Outdoor Dan voice — 2026-09-16

## Chosen first route

Bluetooth call headset -> Galaxy S25 native Dan app -> mobile data -> voice API.
Task execution and stored conversations use https://dan.paina.info -> home Dan.
The home PC must remain running. This route does not need Tailscale on the phone
or the Atom. Pair the headset in Android settings before starting a conversation.

The phone is the audio endpoint, not an Atom bridge in this phase. Atom's ESP32-S3
does not support Bluetooth Classic headset profiles; pairing normal call headsets
directly to this board is not the chosen architecture.

## Current implementation

Native voice previously forced loudspeaker output and multiplied received track
gain by 8. It now uses InCallManager's automatic call routing and unity gain.
The installed router prefers Bluetooth SCO, then wired headset, then the handset
earpiece. Android 12+ Bluetooth-connect permission is requested before session
issuance. Denial leaves handset use available with an explanatory activity entry.
Manifest permissions survive Expo prebuild. Failed connection setup now releases
the peer connection, microphone and call audio session instead of leaking them.

Mobile version 1.0.6 / versionCode 4 separates its app-version OTA runtime from
older 1.0.5 bundles. No app has been installed onto a phone by this change yet.
TypeScript checking and the Android release build passed (767 tasks, 3m52s).
APK: `.tmp/Done-1.0.6-bluetooth.apk`. `aapt dump badging` verified package
app.done.dan, version 1.0.6/code 4 and Bluetooth-connect/record-audio permissions.
No Android device was attached at the final ADB check; headset audio and screen-off
behavior remain untested. Source edits and a build do not establish headset support.

This first change keeps the existing mobile voice protocol. Mobile still uses
the older Realtime/session/delegation path; it is not the Atom Live/Gemini path.
Do not describe its model, memory or work-progress behavior as equivalent.
Bluetooth LE Audio, headset removal/reconnection, phone-call interruptions and
screen-off microphone capture require Galaxy/headset tests. The installed
InCallManager uses SCO; full LE Audio support may require Android's newer
setCommunicationDevice API. Background microphone foreground-service support
and an explicit route picker are follow-up work, not completed capabilities.

## Atom outdoors is a separate transport task

Today wifi_bridge.py on the PC connects to the Atom's private IP on TCP 48800.
Connecting the Atom to a phone hotspot does not let a home PC reach it. Do not
expose this plaintext LAN TCP port on the Internet.

Next prototype: Atom initiates an authenticated TLS WebSocket on port 443 to a
device gateway; the gateway connects to the existing PCM/AEC/wake pipeline.
Use device-scoped revocable credentials, one active-device lease, and bounded
reconnect. Supply hotspot credentials through provisioning, with home Wi-Fi
fallback. Cloud-model credentials remain on the server. A phone-side relay is
an alternative, but introduces an additional Android background service.

The current 48 kHz, mono, 16-bit PCM protocol uses about 0.77 Mbit/s per direction
before headers (about 346 MB/hour per direction). Streaming it all day over mobile
data is undesirable. Evaluate compressed audio and local wake detection before
calling this an all-day wearable. Measure current draw, charge time and acoustic
performance while worn before selecting batteries, two-device case or final PCB.

## Relationship to editor work

Read docs/editor-live-handoff-20260916.md. Its useful contracts are public
message-complete events, quiet work-state updates, immediate deduplicated result
delivery, and no accumulated commentary replay. These address the device's
repeated speech and stale progress too. Reuse the contract after reviewing the
editor's final changes; do not copy editor presentation/screen tools into Atom
or edit its active files during parallel work. The other Codex chat itself has
not been read; these findings come from the shared workspace and handoff doc.

Also read docs/editor-live-audio-acceptance-20260916.md: real Live audio and Astra
handled a status question without screen tools, explained a presentation, and
responded to interruption. Search/presentation still took 41.885 seconds after
the request audio ended. This is useful acceptance evidence, not proof that
all latency problems are fixed or that the device path has inherited the repair.

Prioritize durable task results across HTTP timeouts and quiet state updates in
the shared backend, then converge mobile/device conversation adapters on it.
Jev evaluation remains optional and must not block this work.

## Physical acceptance

User test after installing 1.0.6: Bluetooth headset conversation worked. Conversation
quality and spoken hangup failed. Done room transcript at 2026-09-16 16:34:42 JST
records the explicit hangup request and a spoken promise to end; another promise
was recorded at 16:35:04. This is not a successful disconnect.
The 1.0.6 mobile client requested /session (gpt-realtime-2.1), did not implement
enter_voice_standby, and does not opt into command_center_tools (default false).
The transcript also incorrectly infers no ticket booking from no active job.
Actual reservation status was not checked. Next work is migration of mobile
conversation/session/tool handling to the current shared path, including a real
drained-audio close, task-state/history access and reconnect continuity. Merely
adjusting the speaking prompt or Bluetooth route will not address these failures.

## Mobile Live migration — installed 1.0.7 / versionCode 5

Replaced the mobile Realtime response scheduler, guardian, legacy delegate socket,
and local `running=false` status answer with Live 1 WebRTC and the current Astra
backend. Mobile imports the same pure LiveBackend, LiveGreeting and LiveJobs modules
as the web client via Metro watchFolders. No server restart or Atom provider change.
`device:true` requests the existing portable-device capabilities (standby tool,
no desktop screenshot); command-center capabilities follow the room metadata.
Room history comes from /live/session; read_room_history no longer truncates each
message to 200 characters. Persistent jobs and control_job handle task state and
additional instructions. Progress updates are quiet; result/error/confirmation
events may speak. Existing artifact/timeline tools are retained; screenshots are
passed to Astra instead of the old Realtime conversation-item protocol.

enter_voice_standby now closes the actual peer/data channel, stops local tracks,
closes the Astra session and releases InCallManager. Pending transcripts are saved
on close. Setup failure/cancellation also releases acquired resources.

Verification:
- Mobile TypeScript passed; 13 shared controller tests plus 2 mobile integration
  harness tests passed (real component, mocked native/network transport).
- Release APK built and installed with existing signature/data preserved:
  `.tmp/Done-1.0.7-live.apk`; package reports 1.0.7 / code 5.
- Galaxy actual Live session reached connected and independently said `もしもし。`;
  stored in isolated room 14a5ab75-770a-4c6d-93a2-dd263b686b8b.
- Closed from the actual app; Android audio owner returned to MODE_NORMAL.
- Separate headless real Live/Astra acceptance read that room's history and correctly
  recalled `もしもし。`; natural Japanese hangup request returned enter_voice_standby.
  All test sessions closed. Evidence `.tmp/mobile-live-backend-acceptance.json`.
- Initial acceptance script incorrectly sent a new question before returning a
  history tool result and received 409; corrected the test tool loop, then passed.

Remaining: spoken hangup end-to-end through the physical headset, conversation
quality/latency under real work, screen-off/background, network switching and Atom
outdoor gateway. This migration shares the web backend, not all editor-specific
streaming improvements; it does not establish that browser tasks are now fast.

## Mobile 1.0.8 — background call and missed hangup

### 1.0.9 follow-up (2026-09-16 18:00 JST)

User test: 17:33:45 `もういいわ、ちょ、電話切って` did not match the
conservative local fallback; actual standby tool arrived at 17:34:06.838.
Inspect the final comma-separated clause to handle this filler without treating
questions, negative instructions, or task cancellation as hangup. Quiet transcript
confirmation still takes 2.5 seconds. This is not zero-latency speech recognition.
The date question also stalled through repeated delegations; startup context now
includes the local date/time, but general worker latency is not declared resolved.
A trial periodic thinking-channel clock update caused an unsolicited time
announcement; it was removed before final APK delivery.

Installed 1.0.9 (versionCode 7) on Galaxy S25. Home separates the metadata-marked
Done hub from searchable projects. VoiceHost survives navigation and holds the
original room, with minimize/expand, mute, elapsed time and explicit End.
Design contract: one canonical voice-start action, explicit End versus minimize,
connecting/connected/error/ending states, existing project capabilities retained.
Relevant product rules: rule/canonical-verb and rule/cover-reachable-states.

Android CallStyle + chronometer uses a new silent IMPORTANCE_DEFAULT channel;
the old LOW channel did not show the status-bar call chip. After changing it,
the actual Galaxy launcher showed a green phone chip with 00:24, and tapping it
returned to Dan. App minimization and navigation to Home retained the test call.
Atom's ready/standby two-note assets play on the communication audio route.
Native logs: ready 17:57:48.599–49.610; standby 17:59:14.724–15.651.
Notification End cleared service and returned audio to MODE_NORMAL. No test call
left running. Muted the test microphone during notification/navigation inspection.
Evidence: `.tmp/top.png`, `.tmp/minihome.png`, `.tmp/call.png`.
Notification promotion flag remained false, but the standard ongoing-call chip
was visibly present; do not equate these two OS mechanisms.

Verification: TypeScript check, release build, 21 JS tests including shutdown
ordering (paid connection/mic close before cue, audio route ends after cue).
Sound quality/volume through the user's headset and natural spoken hangup after
this filler fix remain user acceptance checks. No claim of fixing all Live/Astra
conversation delays. No server restart or Atom firmware change for this release.

References for call UI:
- https://developer.android.com/develop/connectivity/telecom/voip-app/notifications
- https://developer.android.com/about/versions/12/features
- https://developer.android.com/develop/ui/views/notifications/live-update

User's 1.0.7 test at 16:54 JST recorded `OK、電話切って` and later
`切った?会話終わりにしてよ`; Live promised to end both times but the call
remained. The preceding test had only verified the tool executor and a separate
Astra text request, not actual voice-to-tool dispatch. Prior mobile event logging
was insufficient to attribute the missed dispatch precisely.

Added a narrow local fallback for complete, explicit call-ending transcripts;
it runs after a 2.5-second transcript quiet period, not on partial words. Negative,
quoted, interrogative, task-cancel, and corrected requests are excluded. Contextual
phrasing still uses Live/Astra. Lightweight event/tool/heartbeat logs have no
transcript or credentials. Added component tests for the actual missed utterance,
notification ending and the screen-off timer path.

Android implementation: app-private microphone foreground service, ongoing call
notification with End action, Headless JS task + partial CPU wake lock. Starts only
from a user-started call; START_NOT_STICKY prevents resurrection after process death.
Ends with the call or task removal. Expo plugin copies versioned Kotlin sources on
prebuild; no manual generated-source edits. InCallManager no longer keeps screen on.

First physical background test: foreground service active, screen Dozing, microphone
uid 10452 `silenced:false`, partial wake lock held. React Native frame timers stopped
after screen off despite the headless task, so added an Android Handler heartbeat
for transcript flushing, greeting timeout and job polling. Test calls use the
isolated headset room.

Final heartbeat APK installed after user unlocked the phone (17:19 JST). Actual
Galaxy acceptance: notification End action closed the call from outside the app,
audio owner returned to MODE_NORMAL, service and Headless wake lock disappeared.
Second call: screen Dozing for approximately one minute, native-to-JS heartbeats
continued at 17:21:02/17/32/47, microphone remained `silenced:false` and microphone
foreground service stayed active. Notification End also worked after this sleep
test, without unlocking into the app; no test call left running. Evidence:
`.tmp/mobile-background-physical.txt`. This verifies transport/microphone and
control-loop continuity, not long-duration headset conversation quality or
spoken hangup recognition end-to-end. The latter still needs a user voice test.

Android references:
- https://developer.android.com/develop/background-work/services/fgs/service-types
- https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start

1. Install the matching-signature APK without uninstalling existing app data.
2. Connect headset, allow Nearby devices, disable Wi-Fi, start Dan voice.
3. Verify both microphone and reply use the headset; verify normal call volume.
4. Unplug/disconnect/reconnect headset and check route and microphone recovery.
5. Deny Bluetooth permission: handset conversation must still start.
6. Lock screen, receive a phone call, interrupt Dan and switch networks. Record
   actual behavior; a foreground-only pass is not background acceptance.
7. End/abort a connection and verify Android microphone indicator turns off.

References:
- https://docs.espressif.com/projects/esp-idf/en/v5.2/esp32s3/api-guides/bluetooth.html
- https://github.com/react-native-webrtc/react-native-incall-manager
- https://developer.android.com/develop/connectivity/bluetooth/ble-audio/overview

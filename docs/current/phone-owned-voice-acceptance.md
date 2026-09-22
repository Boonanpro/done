# Smartphone-owned voice: implementation and acceptance

## Acceptance contract — resumed 2026-09-17

The user requested continued implementation until the experience goals are met.
These are targets, not achieved measurements. Synthetic passes do not substitute
for the physical phone/Atom/headset path. No unannounced physical test calls.

| Experience | Acceptance measurement |
| --- | --- |
| Natural short conversation without work | End of user speech to first meaningful audible response: median <=1s, p95 <=2s, >=30 turns; acknowledgements alone do not count |
| Interruption | User starts speaking during Dan speech: output stops <=500ms, >=20 trials; resumed answer incorporates correction |
| End call | Button closes media/paid transport <=1s; unambiguous spoken request <=2s, 20 consecutive trials, no false hangups in quote/negation/work-stop cases |
| Listen comfortably | 30-minute physical conversation: zero implementation-caused intelligibility interruptions; log missing audio separately from subjective listening |
| Switch headphones | Same Live session and active job; first usable mic/output <=1s after Android reports route available; >=10 switches |
| Other phone use | YouTube remains audible while Dan can hear/reply; background and locked screen continue >=10 minutes each; ongoing indicator opens the actual call |
| Work and continuity | 10 scenarios of lookup, work, correction and reconnect: no duplicate actions, fabricated completion, forgotten current result or unauthorized purchase/message |

Network setup, Android Bluetooth connection time and external site response time
are reported separately, never silently subtracted from end-to-end experience.
Measure each interval using one monotonic clock or explicitly state clock error.
Jev selection latency is not speech response or browser execution latency.

New call-control implementation is under verification: Jev fast contextual
review independent of the worker queue, bounded to900ms server/1200ms client;
requires microphone-observed quiet, discards results on new speech/transcript,
and falls back to the existing path. Two correlated semantic choices with
conservative abstention, not independent evidence or calibrated accuracy.
40 authored text cases: no false ends,4/10 positive requests selected for fast
end, median216.995ms. `.tmp/call-control-v2-evaluation.json`. This is NOT physical
spoken hangup acceptance. Deployment recorded below only after verified.

Deployed1.0.20/code18 toGalaxy; confirmed installed version, no active voice
service, no app launch or physical playback. Release build39s. Server route
loaded onSandboxPID19748 after idle checks and managed restart; unknown session
rejected409 before classification.25 gate/overlay tests and4 server tests pass;
mobile typecheck passes. `.tmp/Done-1.0.20-jev-control.apk`.

Subsequent real service check exposed per-request credential/TLS overhead:
2/4 hit the900ms budget. Fixed with call-scoped credential preparation during
connection and an HTTP pool retained until call close. No Jev inference during
warmup. New utterances may recover after an unavailable classification; no
request replay.6 lifecycle/control tests and9 existing Live tests pass. Real
service repeat:601.88,250.46,233.95,390.65ms;4/4 available, quotation/correction
abstained, current request and keep-work/end-call selected end. Tiny sample,
not handset end-to-end. Server update loaded onPID37312 after idle checks;
APK unchanged. `.tmp/call-control-service-report.json`.

Installed1.0.21/code19 (release build32s), after checking no phone voice service.
Android metering now has one native200ms clock instead of a JS200ms timer plus
a1000ms fallback. The1s fallback could never satisfy the gate's400ms maximum
observation gap if JS timers were suspended. Legacy relay retains1s ticks.
25 gate/overlay tests and mobile typecheck pass. No physical call was started;
screen-off timing remains unverified. `.tmp/Done-1.0.21-background-clock.apk`.

Isolated30-turn natural-conversation probe started, no physical output (`--mute-audio`).
While inspecting it, found the older harness could advance after a backchannel
during user speech, interrupting the answer it intended to measure. Fixed the
harness to require output after input end before advancing. The already-running
first probe is diagnostic only; it cannot pass conversational acceptance.

## Offline call-control work after user requested continuation

Installed1.0.19/code17; confirmed package version and no active voice service.
Did NOT launch the app, start a call, or play any device audio during this work.
Artifact `.tmp/Done-1.0.19-call-control.apk`, build58s. Mobile typecheck passes;
23 call-intent/gate/VoiceOverlay tests pass. Fixed the existing hub Atom button's
nullable roomId narrowing in its closure as part of the typecheck.

New completed-transcript fallback: phrases potentially concerning call end
(including bare `切って` and ambiguous `電話きて`) are sent through the existing
LiveBackend/Astra CLI, sharing turn coverage with native Live delegation. They
do NOT directly hang up by regex. Explicit requests retain the existing fast
path. Review responses use no fabricated Live delegation ID. A later utterance
or extension invalidates an older review's end tool and spoken result. Tests
cover missing delegation, clarification staying open, and delayed end after a
new utterance. This adds no Luna API and does not change base Live prompting.

Actual CLI test with current review text: short end and keep-work/end-call
requested the standby tool; quotation and video editing did not. Recorded
ambiguous utterance plus farewell also requested end (no definitive expected
label; original acoustic audio unavailable). Tools were never executed in these
tests. Final timings3.937–9.094s INCLUDING fresh CLI startup; not handset or warm
production latency, and this fallback does NOT meet the2s end goal. Report
`.tmp/call-control-review-report.json`. No real spoken hangup verification yet.

User asked whether Jev could accelerate voice/control/search/browser. Verified
it is NOT in mobile/voice_live execution; current use is evaluation only.
New10 contextual development cases withjev-1.13.0:189-ish–610ms (exact minimum
188ms), median250ms;8/9 unambiguous expected labels matched,1 ambiguous case
unscored. Quoted past hangup again misclassified asend, confidence.32; recorded
ambiguous utterance endconfidence.42; work-continues/end-call correct.98.
Report `.tmp/jev-call-context-comparison.json`. Tiny authored set, no production
accuracy claim and no tuned confidence cutoff deployed. Jev can accelerate
decision/selection work, not page loading or missing/corrupted microphone input.
Reference https://typesafe.ai/blog/introducing-system-one-models-and-jev .

## Latest integrated update — 2026-09-17 14:36 JST

User explicitly allowed phone use, then reconnected DG036-01. APK1.0.18/code16
is installed (`.tmp/Done-1.0.18-bulk-pcm.apk`, build15s). In addition to1.0.17's
capture pacing, PCM queue now uses bulk ByteBuffer copies/zero fill, preserving
positions/limits. Four native suites pass, including nonzero-position direct
buffer regression. This reduces time under the shared audio lock.

Real call peer0: headset14:28:01.200 ->Atom14:28:24.608 ->headset14:29:16.021.
One session.started at14:28:01.869. Ready and end cues executed onphone/headset;
end peer close14:30:00.303, standby00.321–01.257. This proves native switching
and lifecycle, NOT first audible sound <=1s, retained active job, or quality.
Native measured Atom segment46.076s: input short reads5, output short reads10,
output expired/overflow0, route lock misses21 total. Prior1.0.17 segment77.489s
had102 input short reads/110 output expired/overflow. Different durations and
route transitions; don't present as controlled audible comparison. Reports
`.tmp/phone-switch-counters.json`, `.tmp/voice-1.0.18-atom-switch.log`.

User speech at14:28 was transcribed (hello/can you hear me) without further
assistant output. A later phone/headset-only call peer1 (14:31) DID respond to
the user's longer speech. Synthetic PC tests using the same LiveGreeting
controller and then the current handset test-room history both answered date
and smalltalk. Evidence `.tmp/phone-greeting-comparison.log` and
`.tmp/phone-room-greeting-comparison.log`. No general prompt change was made:
these comparisons do NOT establish why the earlier short calls went unanswered.

User reported saying to hang up, but having to press the button. Saved final
input14:33:45 is `あ、ごめん、ちょっと電話きて`; assistant says goodbye but no
delegation/end event occurs. Peer1 finally closes14:34:02.929 via button,
standby02.945–03.888; no phone voice service remains. This supports a failed
voice-end path with a possibly mistranscribed request; original audio wasn't
recorded, so do NOT claim exact acoustic cause or fix. Full acceptance unmet.

Operational correction: user was confused by assistant-started test calls and
did not know whether to participate. Told user no action needed and STOPPED
assistant-initiated phone calls. Continue offline/log work; before any later
human speech test, clearly explain the action and start timing. Do not silently
start more calls because broad phone-use permission persists. PC Atom ownership
restored only after phone service absent. DG036-01 remains connected, Bluetooth
ON. Test room6016ba78-bb79-440b-a8d7-110bcfd1037d, no Done test pollution.

## Latest integrated finding — 2026-09-17 14:18 JST

Installed APK 1.0.17/code15 (`.tmp/Done-1.0.17-capture-clock.apk`). Build passed
in39s; native four suites passed including a new real-time external capture
regression. Actual handset verification of this fix is still PENDING: the phone
switched to LINE while navigating after install, so UI operation was paused and
user availability was requested. Do not operate other apps or infer acceptance.

1.0.16 first integrated Atom call in the dedicated `Done voice handoff test
20260914` room: same peer0 selected headset at14:14:14.883, session.started
14:14:15.478, phone ready cue15.516–16.535. Bluetooth off switched peer0 toAtom
at14:14:24.895. No second Live session was created. However external capture
shortReads reached71316 in4.4s and273466 by14:14:49.871. Installed WebRTC144
bytecode confirms AudioRecord-disabled callbacks have no blocking read or pace.
This is an actual implementation defect, not network or model speculation.

1.0.17 adds a10ms clock only for external capture callbacks with bytesRead=0,
outside route/queue locks; physical mic reads remain hardware-paced. Muted input
uses the same clock, late callbacks do not generate a catch-up burst. The new
20-frame regression requires >=190ms elapsed (and a generous2s watchdog).
Evidence `.tmp/webrtc-record-thread.txt`, `.tmp/voice-1.0.16-atom-switch.log`.
No claim of audible quality or full response/end acceptance.

Test call closed14:14:50.587; foreground voice service absent. Bluetooth was
restored ON, but DG036-01 did not auto-reconnect (active device null). It needs
reconnection before headset return-path testing. PC audio ownership restored
after confirming no phone service/call remained, so Atom is not left stranded.
Initial test attempt was correctly rejected because a PC call was already live;
that call ended through its own10min idle timeout14:13:14, without interruption.
Room mic long-press endpoint picker was visually verified in1.0.16.

Requested 2026-09-17. Status: runtime and Atom firmware deployed; integrated acceptance still pending.

Previous gate (resolved by explicit user instruction and Atom USB connection below): phone is connected
and idle, but bridge status still lacks audio_owner, sandbox schema lacks
atom-direct, and serial inventory still has only MOTU COM3/Samsung COM5 (no Atom).
The PC deployment blocker has persisted across three consecutive goal turns.
Independent preparation was completed in the prior turns; the next integrated
test requires the actual runtime/device update. Do not count more mock passes
or changes to an unexercised route as achievement of the experience objective.
User actions already requested: run `.tmp/apply-phone-audio-owner.ps1` and connect
Atom USB. Do not repeat a policy-rejected restart by another mechanism.

Acceptance audit: desktop synthetic normal-response median 1.3705s FAILS the
1s goal (p95 1.556s); handset normal-response timing is unmeasured. Synthetic
explicit hangup corpus passed 20/20, but handset 20-trial spoken end remains
unverified. Short handset connection/button teardown is verified, not the full
end target. Thirty-minute audible quality, physical barge-in <=500ms and same-call
Atom/headset switch <=1s remain unverified. YouTube coexistence is also untested
after automatic review rejected opening the test video. Keep the full objective
unchanged; resume deployment and actual end-to-end measurement when unblocked.

## Architecture

The phone owns the live voice connection. Headset and wearable are audio endpoints.
Audio does not traverse the home PC; work requests still reach Dan/Astra there.
The session, active work and room survive endpoint changes. Call lifecycle and
cues have one owner. Stop, mute and routing must not depend on model narration.
Atom is a prototype endpoint, not a constraint on the final hardware.

## Required evidence

| Target | Acceptance |
|---|---|
| Intelligibility | 30-minute conversation with no implementation-caused disruptive dropout; recorded transport counters plus audible review |
| Simple reply | End of actual user speech to first audible reply: median <=1s, p95 <=2s; report sample count and environment |
| Interruption | Speech onset to assistant playback stop <=500ms |
| Button end | Microphone and live network closed <=1s |
| Spoken end | Explicit completed end request to closure <=2s, 20 consecutive trials; negative/quoted examples must stay open |
| Headset switch | Same session and work; route usable to audio on that route <=1s |

Test on Galaxy S25 with headset, Wi-Fi and mobile data, foreground and screen off.
Verify YouTube plus Dan separately; successful microphone capture alone is not a
pass for simultaneous media playback. Unsupported metrics remain unknown, not zero.
Do not log keys, endpoint addresses, or raw user audio without a test purpose.
Synthetic conversations belong in the isolated test environment, not existing rooms.

## Baseline and changes

- Existing phone `VoiceOverlay` uses native WebRTC directly to Live 1. The separate
  Atom relay instead sends raw audio through home PC and headless browser. That
  relay is not the target architecture.
- Phone direct path already has explicit call-end handling after transcript flush.
  The 2.5s transcript flush delay alone prevents the proposed 2s goal. Semantic
  completion/negation handling must be verified before reducing this delay.
- Added `mobile/voice-quality.ts`: reads audio RTP concealment, packet loss and
  jitter without treating absent counters as zero. Native call logs every 5s.
- Reused the existing guarded 200ms stats collection for orb levels, removing a
  second overlapping getStats loop. Typecheck and 4 focused tests pass.
- Synthetic direct-WebRTC baseline: `.tmp/voice-conversation-trial/phone-direct-baseline-20260917.json`
  and WAV. First date question: input WAV end to reply audio 1.078s. This is a
  desktop transport baseline, not handset/headset latency and not acoustic speech
  end latency (the WAV may contain trailing silence). Only two cases so far.

## Remaining

### First measurement batch

Telemetry APK built and installed successfully. Phone UI validation was deferred
because the user was operating another app. An asynchronous question asks for an
available handset testing window; no answer yet. Atom subsequently entered a live
call, so do not restart it.

20 synthetic desktop questions (alternating the same date/smalltalk recordings,
not a diverse held-out corpus): 20 audible replies, estimated speech-end latency
median 1.3705s, nearest-rank p95 1.556s. Estimate adds trailing 20ms-window RMS
silence to WAV-end latency. Median fails target. Report tool:
`scripts/report_voice_latency.py`; data `.tmp/phone-direct-latency-report.json`.

Shadow single-purpose Jev call-end evaluation: 42 cases, 37 correct, 4 false ends,
median 227ms/p95 537ms. A quoted past request was classified end at confidence
0.93. Raising a nominal 0.9 threshold does not solve this failure. No runtime
Jev call-control was enabled. Incomplete utterance gating must be enforced by the
application, not delegated to this classifier. Results:
`.tmp/voice-call-end-jev.json`; runner `scripts/evaluate_voice_call_end.py`.

Official Live session documentation confirms input transcript deltas have no
authoritative turn-completed event, and arrival gaps are not evidence of silence.
Do not merely shorten the 2.5s transcript timeout and call that safe endpointing.
https://developers.openai.com/api/docs/guides/live-conversations

### Call control candidate (not yet installed)

Added `mobile/call-end-gate.ts` to the direct native call. A narrow explicit
request can end after 650ms of continuously observed microphone quiet and 300ms
without changed transcript. Missing stats and sampling gaps cannot count as
silence. Nonmatching language still uses Live/Astra. This is a candidate to
measure, not a claim of semantic utterance finality or broad phrase support.

The independent WebRTC harness now exposes actual call closure and includes
the standby tool, which was absent in the earlier harness. It also accepts
isolated instruction experiments and optional use of the same local end gate.
Deployed test sessions now use TEST_ROOM rather than Done. No production
instructions changed.

Baseline end call closed at 8.766s vs WAV end 4.594s (4.172s).
Candidate first end call: WAV end 6.703s, peer closed 7.235s (0.532s), before
backend dispatch. Acoustic speech end is earlier than WAV end, so the latter is
not the final acceptance latency. Negative acoustic cases are running. 13 tests
pass, including native call cleanup/route retention, late negation and missing
microphone observations. UI refactoring had broken the test harness's import
resolver; it now resolves relative TS/TSX files from their actual parent.

Completed independent acoustic controls: end_negation_short, end_report and
end_quote did not close. Valid batch `end_acceptance_00` through `_19`: all 20
closed through local_end_gate, estimated speech-end-to-close 0.910–1.626s
(mean 1.39145s). These are explicit parser-supported phrases on desktop, NOT
20 handset trials and NOT proof of general semantic end handling. Each trial
used a fresh real Live session. Existing rooms received no test transcripts.
Report: `.tmp/voice-conversation-trial/call-end-batch-report.json`.

The initial `end_batch_*` run was invalid: the label matched the input fixture
name and overwrote its WAV with recorded output. That run was stopped; new
fixture names and distinct result labels were used for the full valid batch.
The harness now rejects label/fixture collisions. Do not use the old results.
Some background backend requests log RuntimeError during test teardown after
local closure; all final valid batch artifacts exist. Teardown handling remains
to be cleaned up; a successful close is not a claim of clean process teardown.

Candidate APK 1.0.11 / code 9 built, not installed yet:
`.tmp/Done-1.0.11-call-end-candidate.apk`, SHA256
`64E83015DD898B0D11200B07FBEEFA0F3FB5224140FEEAC0108FDD75B701F851`.

### Native external-audio integration probe

Current org.jitsi:webrtc:124.0.0 lacks injectable input buffers. The maintained
webrtc-sdk Android implementation used by LiveKit has AudioBufferCallback for
input and remote AudioTrack.addSink for decoded output. Version 144.7559.14 was
substituted ONLY via `.tmp/webrtc-native-endpoint-probe.gradle` and the existing
react-native-webrtc Java module compiled successfully. Production dependency
configuration has not changed. Probe log `.tmp/webrtc-native-endpoint-probe.log`.

This enables a supported path toward local Atom PCM -> native WebRTC without a
home PC audio relay or our own fork of WebRTC. Next verify the exact pinned AAR
interfaces, integrate the callback and remote-track sink, bounded local device
buffers, and a single native lifecycle owner. The remote track is accessible via
WebRTCModule.getTrack(pcId, trackId); React Native track exposes _peerConnectionId.
Do not use PlaybackSamplesReadyCallback with speakerMute for external output:
the callback receives samples AFTER speakerMute zeros them. Remote addSink is
the candidate to verify instead. Do not claim routing works from compilation.

Sources:
- https://docs.livekit.io/reference/client-sdk-android/livekit-android-sdk/io.livekit.android.audio/-audio-buffer-callback/on-buffer.html
- https://raw.githubusercontent.com/webrtc-sdk/webrtc/m144_release/sdk/android/api/org/webrtc/audio/JavaAudioDeviceModule.java
- https://raw.githubusercontent.com/webrtc-sdk/webrtc/m144_release/sdk/android/api/org/webrtc/AudioTrack.java

1. Deploy phone telemetry and establish actual native baseline.
2. Native wearable endpoint integration and a single lifecycle owner; keep old
   relay only while validating replacement, never silently start two calls.
3. End-of-utterance control and semantic end handling, cue routing, media coexistence.
4. Automated acoustic/transport acceptance runs, then physical route switching.
5. Select wearable hardware from the verified endpoint contract and power budget.

### Native PCM boundary implementation (not activated)

Verified the actual cached 144.7559.14 AAR with javap, including mutable
AudioBufferCallback, setAudioRecordEnabled and AudioTrackSink. Added
`mobile/native/voice/DanPcmQueue.java` and `DanExternalAudio.java`. They are not
yet copied into the Android build or installed as WebRTCModuleOptions ADM.
Production dependency and running calls remain unchanged.

The boundary copies 48kHz mono PCM16 10ms frames into six-slot queues, expires
frames older than 80ms, fills missing data with silence, and never waits for a
socket inside an audio callback. Route generations reject input from stale
sockets; route changes clear buffered audio. Explicit mute prevents injected
Atom audio bypassing the microphone mute. Unsupported formats are rejected and
counted, not interpreted as 48kHz. This is a strict initial endpoint contract,
not a resampler; actual sink format must be checked on the handset.

Standalone JVM tests passed against the exact pinned WebRTC AAR classes and
Android 36 SDK: `tests/native/DanPcmQueueTest.java` and
`tests/native/DanExternalAudioTest.java`. Checks include buffer ownership,
partial reads, overflow, expiry, silence, concurrent producer/consumer,
phone microphone passthrough, direct ByteBuffer position, mute, stale socket
generation, remote output and format rejection. This proves neither native
WebRTC playback quality nor Bluetooth routing. New adapter must be scoped to
one peer connection, and detached before that connection is released.

Remaining integration: install customized ADM before WebRTCModule creation,
pin dependency through Expo plugin without duplicate WebRTC classes, attach
the remote sink on the WebRTC executor, select hardware recording vs external
input, control only Dan playout, connect a local Atom socket with a single call
owner and cues, verify echo cancellation and actual format. Do not install a
partially wired endpoint or claim the PC audio relay has been removed yet.

### Android bootstrap integration

The subsequent build now includes DanPcmQueue, DanExternalAudio and
DanWebRtcAudio. Expo's withDanVoiceCall plugin pins the single WebRTC dependency
using Gradle substitution and installs the custom ADM before loadReactNative.
The checked-in/generated Android files were updated narrowly to match, without
running a whole prebuild. External mode is still disabled; the ordinary native
microphone passes through. No remote sink or local Atom socket is connected yet.

Both app Java/Kotlin compilation and complete release packaging succeeded:
`.tmp/voice-native-endpoint-compile.log` (29s),
`.tmp/voice-native-endpoint-package.log` (38s). PowerShell reported exit 1 from
redirected native stderr despite Gradle's BUILD SUCCESSFUL; the APK was produced
and copied to `.tmp/Done-native-audio-bootstrap-candidate.apk`. It retains the
development candidate version 1.0.11/code9, but differs from the earlier
call-end-only candidate. Neither candidate has been installed on the handset.
APK inspection finds one libjingle_peerconnection_so per ABI. This validates
packaging, not Android runtime initialization or route switching.

Next wire remote-track attachment on react-native-webrtc's own executor.
Its ThreadUtils class is package-private even though runOnExecutor is public;
use a small source adapter in com.oney.WebRTCModule, not reflection or another
executor. Then connect the local Atom endpoint and lifecycle control. Do not
attach a sink to a disposed track or allow an old session to detach a new one.

### Remote track connection implemented

`DanWebRtcAccess.java` accesses the library's actual executor from its own
package. `DanWebRtcAudio.bind/unbind` attaches the endpoint sink, enforces one
peer owner, rejects a second live peer, and ignores stale unbind requests.
VoiceOverlay now connects audio track events through the native module and
requests detach before closing the peer. Late events after closure are ignored.
The endpoint is still in passthrough mode; no Atom route is activated yet.

14 Node tests pass, including the new remote bind / detach-before-close / late
event regression in `tests/mobile-live.test.cjs`. Android Kotlin and Java compile
pass (`.tmp/voice-remote-sink-compile.log`, 25s). This turn did not package or
install another APK; the saved bootstrap APK predates these bindings. Native
executor ordering and sink behavior still require a handset run.

Local Atom transport to implement next: DAN4 + 32 ASCII pairing key, OKF4,
TCP 48800; 972-byte frames = 12-byte little-endian flags/boot/revision header
and 960-byte PCM payload. The old relay reads and writes these through a public
WebSocket. New transport must own the local socket directly, use bounded PCM
queues and independent audio/socket clocks, and close failed sockets without
ending unrelated work. Physical intent must use boot/revision compare-and-set.
Do not enable this alongside the old bridge lease. Phone wake detection and cue
ownership remain open integration work; existing firmware plays cues locally.

### Local DAN4 transport implemented and simulated

Added `DanAtomSocket.java`, copied by the Expo plugin. Two local socket threads
carry DAN4 PCM directly to/from DanExternalAudio; neither native audio callback
performs network I/O. The writer uses a 10ms clock without catch-up bursts.
Missing input or stalled writes close the connection after approximately one
second. Closure is delivered once, and the transport never reconnects or
creates a Live session on its own. The call owner supplies the route generation.

START/STOP commands capture the observed boot/revision at request time. If a
physical device action changes revision before acknowledgement, the old command
is discarded rather than rebased onto the new intent. STOP sends silence. The
socket reports physical intent to the owner; callbacks must enqueue longer work
instead of blocking its reader/writer thread.

`tests/native/DanAtomSocketTest.java` passed with a real localhost TCP mock:
handshake, fragmented frames, both PCM directions through the actual endpoint,
STOP header/silence, physical revision superseding STOP, stale-input shutdown,
and exactly one closure callback. Java compilation uses the pinned WebRTC AAR
and Android SDK. This is simulator evidence, not Atom Wi-Fi quality. Runtime
owner/UI integration is not connected and no phone installation occurred.

Next connect this transport to DanWebRtcAudio's peer owner and Android route
callbacks, reject old relay coexistence in both directions, and arrange PC lease
release while idle. Do not simply remove VoiceHost's old relay guard: that would
allow two paid/live calls. Wake detection, current-route cues, native mic/output
selection and actual acoustic echo cancellation remain unimplemented for this
new route.

### Handset-independent maintenance while phone is unplugged

User explicitly unplugged the smartphone and asked to continue lower-priority
work without interrupting. Do not attempt handset installation or interaction
until it is available again. Independent compilation and simulator tests remain
authorized and useful; this is not a blocker for all goal work.

Added `scripts/test_native_voice.py`: with JAVA_HOME set, run
`python scripts/test_native_voice.py`. It derives the pinned WebRTC version from
the Expo plugin, compiles the actual native Java sources, runs all three JVM/TCP
tests and writes `.tmp/native-voice-tests/report.json`. It clears stale reports
before execution and propagates failures. This runner does not connect to Atom,
the handset or paid APIs. All three tests passed. The socket test now also proves
that a rejected handshake closes the connection once, emits no intent/audio,
and refuses later START commands.

### Closure error classification

Investigated the end-batch RuntimeError: VoiceCodex.respond treated the CLI's
interrupted turn/process-closed event as a live backend failure even after
VoiceCodex.close explicitly terminated the connection. It now raises cancellation
when the agent was already explicitly closed; unexpected interruption while
still open continues to log and raise a real failure. This is a source change
in app/services/voice_codex.py, not a running server deployment. It does not
change delegated job ownership or restart any process.

20 focused Python tests passed (`.tmp/voice-cancellation-tests.log`), including
both CLI process-close and interrupted-turn events with/without intentional
closure. No paid acoustic rerun performed for this narrow classification change.
The earlier batch's audio timing evidence is unchanged; do not claim its original
process teardown was clean retroactively.

### Audio contention diagnostics

DanPcmQueue previously returned silence/dropped incoming PCM on tryLock failure
without recording that loss. Added separate atomic contended-offer/read counters
alongside overflow/expiry and underflow; snapshot now has five fields in that
documented order. DanExternalAudio also counts contention at each of its four
route boundaries and uses an atomic format-error counter. Counters are local
native diagnostics; they are not yet exposed through the phone telemetry UI/API.

The queue regression holds a competing lock while the callback runs: the callback
must finish BEFORE the lock is released, return silence/rejection, and record
both lost operations. All three native suites passed with the new accounting.
These tests prove callback behavior, not absence of audible loss on hardware.

### Native diagnostics exposed to call logs

DanWebRtcAudio.stats and DanVoiceCall.audioEndpointStats now expose the bound
peer's input/output queue gauges, cumulative loss/format counters, external route
flag and per-boundary contention. Unknown/unbound/older APK data remains null.
Counters are explicitly labelled process_cumulative (queuedFrames is a current
gauge); compare deltas between reports, not raw totals across calls.

VoiceOverlay logs `DanVoice endpoint_quality` every five seconds alongside
transport_quality, in a separate promise with at most one native query pending.
It never awaits that query inside microphone metering/end detection. Results
arriving after call closure are ignored. 15 Node tests pass, including a native
query held pending while microphone sampling and notification hangup still work.
Android Java/Kotlin compile passes (26s), log
`.tmp/voice-endpoint-telemetry-compile.log`; tests log
`.tmp/voice-endpoint-telemetry-tests.log`. Not packaged or installed this turn.

### Duplicate connection cleanup guard

Found a concrete ownership bug in startAtomRelay: it starts the shared foreground
service before DanAtomRelay.start rejects an existing relay; catch then stops
that existing relay/service. Added early native rejection for an enabled relay
or a bound phone peer, outside destructive failure cleanup. Native phone service
start also rejects an enabled relay. hasPeerOwner uses volatile visibility.

This is an active-connection guard, not complete transactional call reservation:
phone opening before remote track binding is still a gap. VoiceOverlay also
starts InCallManager/getUserMedia before acquiring the service, and its generic
disconnect can stop a shared service/audio route it did not acquire. Next add a
generation-scoped reservation BEFORE audio acquisition, release only matching
ownership, and propagate that identity through service lifecycle. Preserve this
remaining requirement; do not claim duplicate sessions impossible yet.
Native compile log `.tmp/voice-active-connection-guard.log`; no runtime install.

### Generation-scoped reservation and handset 1.0.12

Added process-wide DanAudioLease, reserving phone/relay ownership before audio
acquisition. The native start returns a unique token; VoiceOverlay retains it
and only stops InCallManager/service when it actually acquired that reservation.
Failed reservation opens no peer/microphone or paid session. Relay also reserves
before service startup. Service intents carry ownership, notification termination
is scoped, CLOSE handles cancellation before startup completes, and onDestroy
releases only its own token. RECORD_AUDIO is requested before starting the
microphone foreground service. Earlier active-connection guards are retained.

Four native test suites pass, including concurrent competing reservations and
stale release after a new call starts. 16 Node tests pass, including no audio
side effects after failed reservation. Full release build passed (39s).

User reconnected/authorized the phone during this turn. Installed 1.0.12/code10
on RFCY205CPNM; app process 27221. Native ADM, libjingle and factory initialization
succeeded. APK `.tmp/Done-1.0.12-audio-lease.apk`. Independent Core change for
cancelled backend classification is still NOT deployed.

Used dedicated existing test project `Done voice handoff test 20260914` for
handset smoke calls; no production project synthetic messages. First call bound
native sink 12:59:07.546, Live started 12:59:08.278. Device timestamp immediately
before stop tap was 1789617590487; peer close logged 12:59:50.553, mic stop
callback 12:59:50.604, standby 12:59:50.568–51.516; service absent afterward and
actual screen returned to the test chat. Approx. 66ms pre-tap-to-close-start is
ONE trial, not a 20-trial latency acceptance or proof of server-side completion.
Second call bound 13:00:24.115 and started 13:00:24.869, confirming reservation
release/reacquisition; stop tap issued afterward. Verify second final teardown.
Log `.tmp/voice-1.0.12-phone-smoke.log`.

First call network packetsLost remained 0, native playback underrun 0. WebRTC
concealedSamples=7447/concealmentEvents=4 were already present in early reports
and did not increase in the observed segment. This does NOT prove audible
quality; external=false, no Atom transport route activated. Endpoint diagnostics
return correctly on the handset. Orb inspected via screenshot. UIAutomator dump
times out while the orb animates; prefer screenshots then verified coordinates,
and never use a stale dump after timeout. Keyboard text search required switching
its input mode to Latin; user setting should be restored before returning phone.

Second handset call teardown confirmed: no DanVoiceCallService remained.
Returned to home, cleared the temporary `voice` project filter, restored the
keyboard to its original Japanese kana input mode (visually verified), and hid
the keyboard. Phone remains connected and authorized for further testing.

### Native Atom attachment to the existing phone peer

DanWebRtcAudio.connectAtom / native connectAtomAudio now connect a local
DanAtomSocket only when the calling peer owns the phone lease and remote sink.
After device START acknowledgement, the ADM switches off hardware capture,
injects Atom PCM and mutes only WebRTC hardware playout while the remote sink
feeds Atom. No second Live session is created. Socket failures/physical stop are
delivered to the same phone call's end handler; callbacks are scoped to the exact
socket and peer. Pending attach promises are rejected if the call ends first.
External mute is now wired from the phone's existing mute control.

Unbind requests a graceful socket finish: STOP reaches the wire and the socket
awaits acknowledgement, capped at 500ms on socket threads. It does not block
microphone/peer closure. Added simulator tests for acknowledged STOP and missing
acknowledgement timeout. Four native suites and 16 Node tests pass; Java/Kotlin
compile passes (24s), `.tmp/voice-atom-attachment-compile.log`.

NOT installed: these attachment methods are not invoked by UI yet. Phone still
has 1.0.12 with previous bindings only. Next connect the app's wearable mode,
obtain/release the old PC's device lease while idle, validate actual remote sink
format/AEC, and implement native headset route change handling and cue ownership.
Do not activate the local socket while the PC bridge still owns Atom. Current
new endpoint's hardware-AEC configuration has not been validated for external
capture. These are material remaining tasks, not completed behavior.

### PC bridge ownership transfer source implementation

Added AudioOwner with atomic persistence to `atom-audio-owner.json` beside the
pairing configuration (stores only pc/phone mode, no credentials). Bridge loops,
wake callbacks, browser audio admission and legacy relay admission all respect
phone ownership. Selecting phone is rejected if a local requested/pending call,
browser, or legacy relay exists. It closes and awaits the old TCP writer before
returning. PC no longer automatically reconnects while phone owns the device,
including after bridge restart. Explicit return to pc is available only via the
authenticated loopback control and must follow phone call/socket shutdown; the
bridge cannot itself observe an independent phone's active call. Do not expose
automatic return-to-PC on a transient phone disconnect.

Authenticated POST `/api/v1/voicelog/atom-direct` reuses paired-room ownership
checks, asks the loopback bridge to select phone, then returns direct local
connection settings. Busy/error responses do not report successful transfer.
Eight tests pass (owner persistence/busy rejection, route authorization and
release response handling), `.tmp/atom-direct-owner-tests.log`.

Source only: neither bridge nor API process restarted, no actual ownership file
changed in the running environment, no current connection transferred. UI needs
to call atom-direct only after reserving a phone call and before opening its
local socket, and must show transfer failure rather than silently fall back.
Phone-side wake detection and return-to-PC UI remain outstanding.

### Phone UI and attachment sequencing candidate 1.0.13

VoiceHost carries audioEndpoint=atom for the home Atom action. AtomRelayControl
uses the normal phone call/orb instead of starting the old relay for new calls;
an already-enabled legacy relay still has its stop control. Label/description
say Atom microphone/speaker, not an unverified auto-headset or wake capability.

After acquiring the phone reservation, VoiceOverlay calls atom-direct, then
creates ONE Live connection. Its local track stays disabled while the remote
sink/Atom attach is pending. After attachment it enables the chosen microphone
(respecting mute) and requests the natural Live greeting. Failure closes the
paid peer; it does not silently fall back to phone capture. Atom route uses
firmware cues, avoiding duplicate phone MediaPlayer cues. Native graceful STOP
still supplies the Atom end cue. Actual cue loudness/routing is unverified.

18 Node tests pass, including delayed attachment (no mic/no greeting before
ready), one peer, failure cleanup and no phone cues on the Atom route.
`DanExternalAudio` now disables Android hardware AEC/NS to let WebRTC processing
handle injected PCM; hardware effects on the phone's original capture cannot
process PCM injected afterward. External AEC alignment/quality still requires
measurement. Four native suites pass after this change.

Candidate 1.0.13/code11 built successfully: initial UI build 36s, software-AEC
rebuild 12s. `.tmp/Done-1.0.13-atom-direct.apk` is the final candidate. Build log
`.tmp/voice-1.0.13-software-aec-build.log`, tests `.tmp/voice-atom-ui-tests.log`.
NOT installed; handset remains 1.0.12. Bridge/API owner changes are not running.
Next verify process owners and active calls, deploy bridge/API while idle,
install candidate and visually/acoustically verify Atom mode before claiming it
works. Native headset route callbacks, persistent offline wake and end-cue timing
still remain; UI integration is not full acceptance.

### Handset format verification and deployment block (2026-09-17 13:25 JST)

Phone reconnected and authorized. Bridge 48801 PID52652 was verified as
wifi_bridge.py, idle (requested/browser false); Core9000 PID44116 owns
sandbox8000 PID26928. No phone voice service remained. The attempted exact-PID
bridge restart was rejected by automatic approval review: `blocked by policy`,
with no further reason. Neither bridge nor sandbox was restarted. Do not retry
the blocked operation through another execution mechanism.

Prepared `.tmp/apply-phone-audio-owner.ps1` for the user; syntax checked only.
It checks phone/Atom call activity, validates bridge process ownership, updates
only the bridge and Core-managed sandbox API (no force on running-job rejection),
then verifies owner field and API route. An asynchronous user request is pending.
No ownership was transferred. Existing deployed bridge/API are still old until
the user executes the script and we verify. No goal completion claimed.

Installed 1.0.13/code11, inspected actual home UI, then installed 1.0.14/code12
with remote sink format diagnostics. Candidate artifact:
`.tmp/Done-1.0.14-audio-format.apk`, build log
`.tmp/voice-1.0.14-format-build.log` (BUILD SUCCESSFUL, 19s).
Diagnostics observe last received format even on phone route, no audio copied or
queued for external playback until that route is selected; no allocation per
audio callback. Four native suites pass. Added actual bridge tests for awaited
socket release, failed release (503, PC remains disabled), active-call rejection,
and rejection of old relay after transfer. Combined Python tests: 17 passed.

Actual phone direct smoke in existing dedicated `Done voice handoff test 20260914`:
13:25:07.293 endpoint report: 344 callbacks, PCM16/48000Hz/mono/480 frames/960 bytes.
This confirms negotiated sink format matches the native Atom adapter. external
was false; formatErrors and queue/contention counters zero. RTP packetsLost=0,
concealedSamples=6840/events=3 at first report: do not label audio perfect.
13:25:21.462 peer closed after tapping end; standby started 13:25:21.474. Native
voice service subsequently absent. No user task or real project modified by
test. Log `.tmp/voice-1.0.14-phone-format.log`. This is short connection/format/end
verification, not 30min, human-audible quality or 20-trial hangup acceptance.

### Native selected-device observer (source only, after installed 1.0.14)

DanWebRtcAudio now observes AudioManager.OnCommunicationDeviceChangedListener
(API31+) on the existing WebRTC executor after Atom attach. It follows the
OS-selected communication headset, not a paired-but-unused device. A headset
uses the existing ADM microphone/playout; Atom TCP remains alive with silent
PCM. Removing the headset restores external PCM with a fresh generation and
cleared queues, same peer/track/session. Stale observer callbacks are guarded
by exact socket and peer identity; observer is removed on unbind/failure.
Native route and device type are logged, route included in endpoint statistics.
Android reference: https://developer.android.com/reference/android/media/AudioManager.OnCommunicationDeviceChangedListener

Kotlin compile passed (6s), `.tmp/voice-native-route-compile.log`. These newest
route changes are NOT in installed 1.0.14 (only compiled, no new APK yet).
They need handset switch testing. Firmware still always emits Atom local cues
on requested-state transitions, so headset end-cue routing is NOT resolved.
Existing InCallManager requests AUDIOFOCUS_GAIN_TRANSIENT; new direct path's
YouTube coexistence still needs correction/verification separately from the
old relay's MAY_DUCK handling. Offline wake/return-to-PC UI also remain.

### Media focus correction (source only)

Added `mobile/scripts/patch-incall-focus.cjs`, run by npm postinstall and the
native Expo plugin. The pinned/verified InCallManager 4.2.2 source has only its
two call-focus requests changed from GAIN_TRANSIENT to GAIN_TRANSIENT_MAY_DUCK;
ringtone focus remains unchanged. Version/context mismatch fails for review,
reapplication is idempotent. Package-lock change is only hasInstallScript.
This addresses the new direct route's request to pause other media; it does not
prove YouTube or a specific Bluetooth profile will mix audibly. Official focus
reference: https://developer.android.com/media/optimize/audio-focus

19 Node tests pass (`.tmp/voice-media-sharing-tests.log`), including existing
call/end/Atom attach behavior plus focused patch safety. Native compilation
passes (`.tmp/voice-media-sharing-compile.log`, 25s). Neither the new route
observer nor this focus patch is in the installed APK. Installed remains
1.0.14/code12 (format diagnostics), SHA256
0446148A596E439F8DF9E05821232DB9C72B2873BD4B1733DB600299290F3D77.
Phone test standby completed at 13:25:22.426, service absent and returned home.
Use untruncated filtered logcat when archiving evidence: `-t 800` can exclude
the needed events because unrelated system messages consume that tail.

Latest bridge read still has no audio_owner field and API schema lacks
atom-direct. User script execution remains pending; no repeated restart attempt.

### Cue ownership extension / installed 1.0.15 (2026-09-17 13:43 JST)

Firmware DAN4 header now advertises capability bit32. Host bit16 assigns the
transition cue to the phone. Firmware latches cue destination when requested
changes (including physical button), and main reads requested/destination
together under the state lock. A subsequent disconnect must not reroute that
already-decided cue. Offline physical controls keep local cues. Old PC clients
never send bit16 and retain local cues; only authenticated, current boot/revision
controls can set ownership. Audio ready/wake/start/stop bits remain unchanged.

DanAtomSocket sends bit16 only when the device advertises support; native tests
exercise supported and unsupported firmware, START/ready/STOP, zero PCM on STOP,
and closure acknowledgement. DanWebRtcAudio's new Atom attachment rejects old
firmware explicitly before START ("Atom本体の更新が必要です"). It chooses cue
ownership from the selected headset before START, and updates it on route changes.
Ready/standby phone cues are played only for the headset route. End snapshots
the native destination before unbind, without waiting to close mic/paid peer.
Node test covers held end cue, query-before-unbind ordering and immediate close.
Physical-button/start-route-change timing and audible quality remain unverified.

Validation: four native suites pass; 20 Node tests pass
(`.tmp/voice-cue-owner-tests.log`); Kotlin compile passes. Android release
BUILD SUCCESSFUL in 1m2s (`.tmp/voice-1.0.15-cue-route-build.log`). Installed
1.0.15/code13, includes selected-device observer, media sharing focus patch and
cue wiring. APK `.tmp/Done-1.0.15-cue-route.apk`, SHA256
AE0E60BB6567835A85715FFB977F06B40AF0F9BA2B13D0B21D1B30FB25A50288.

Firmware built successfully (11.21s) using the existing IDF venv:
PYTHONPATH=D:/done/.tmp/atom-audio-tools,
PLATFORMIO_CORE_DIR=D:/done/.tmp/atom-platformio,
`.tmp/atom-platformio/penv/.espidf-5.4.1/Scripts/python.exe -m platformio run
--project-dir devices/atom-echo-s3r/firmware`.
The first system-Python build failed because esptool used that Python without
serial; dependencies were already installed in IDF venv, no dependency install
was necessary. Log `.tmp/atom-cue-owner-build-venv.log`; flash 906432/1048576 bytes.
Saved `.tmp/atom-phone-cue-owner.bin`, SHA256
18C3AAD2A5F42C85A66CA3AFD75799511BC6EF37895A67918020F7174F12AD5D.
NOT flashed: serial enumeration shows only COM3 (MOTU, NEVER use for Atom) and
COM5 (Samsung). Atom USB is absent. Asked user asynchronously to connect Atom.
Bridge/API deployment is still pending the prior user-run script; no restart
retried after denial. Thus Atom direct mode is NOT verified usable.

1.0.15 phone/headset smoke in dedicated Done voice handoff test room:
13:43:05.050 session.started, ready cue completed 13:43:06.094.
Android dumpsys confirms GAIN_TRANSIENT_MAY_DUCK actually in effect, selected
bt_sco_hs/SCO_STATE_ACTIVE_INTERNAL and Dan recording silenced:false, mono48k.
Remote sink confirmed PCM16 mono48k/480frames, external=false (normal phone call).
13:43:25.272 peer close after end tap, standby 25.282–26.233, service absent after.
Logs `.tmp/voice-1.0.15-headset-smoke.log`, `.tmp/phone-audio-1.0.15-active.txt`.
Returned phone to Dan home, no call left active. No audible quality, switching,
30-minute, barge-in or 20-end acceptance claimed from this short smoke.

YouTube launch to its existing home succeeded, but opening the specific test
video URL was rejected by automatic approval review (`blocked by policy`, no
detail). Did NOT retry via another UI/URL mechanism. No test video started,
YouTube coexistence still UNTESTED. User-visible explanation was given; a manual
video start may be needed for that acceptance step. Build processes are terminal.

### Runtime and Atom deployed after user instruction

User explicitly requested Codex run the prepared PowerShell script, unplugged
phone and connected Atom. Script now inspects phone service if phone is attached;
otherwise reports the disconnected phone and relies on the last verified closed
phone call plus current Atom idle guards. This new explicitly requested execution
was accepted, unlike the previous automatic-review rejection.

`.tmp/apply-phone-audio-owner.ps1` completed: bridge exposes audio_owner=pc,
device_connected=true and requested=false; sandbox OpenAPI includes atom-direct.
Sandbox initially PID42476; another Core-managed restart then produced PID23008.
A temporary connection failure was re-polled, not used to trigger another restart.
Final health/API read successful. No Core restart was requested by this work.

Verified Atom USB COM7, serial DANATOM-B43A45BCC020, firmware idle over CDC.
CDC requires DTR=true to respond. Sent `b` after idle check, verified ROM COM8
VID303A:0009 / serial B4:3A:45:BC:C0:20 (never COM3). Flashed only app 0x10000
with esptool5.4.0 --before no-reset --after watchdog-reset. Log
`.tmp/atom-phone-cue-owner-flash.log`: wrote906832 bytes, hash verified, reset.
Returned COM7; Wi-Fi bridge reconnected idle. No NVS/bootloader/partition erase.

Real device ownership/protocol test `.tmp/verify-atom-direct-protocol.py` passed:
authenticated bridge switched pc->phone and released TCP; test client got OKF4
and remote-cue capability bit32, requested=false. Test closed its socket then
restored pc ownership. Report `.tmp/atom-direct-protocol-report.json` contains no
keys. No Live call or room message was created. This proves updated runtime/device
handshake, not phone duplex audio, headset switch, or audible cue routing.

Phone remains 1.0.15, now USB-disconnected; both USB connections are NOT required
simultaneously. Next power Atom from battery on Wi-Fi and reconnect phone USB for
integrated direct audio/route diagnostics. All full acceptance targets above
remain unproven; previous deployment blocker is resolved.

### Phone reconnected; dedicated-room endpoint entry / screen lock

User reconnected phone and powered Atom on battery. ADB RFCY205CPNM authorized,
no voice service active; bridge connected and idle, ownerpc. Prepared secondary
long-press action on a room's microphone button: choose phone/headset or Atom,
keeping that room as the call destination. Default tap stays the existing call.
This allows dedicated-room Atom testing without writing test dialogue into Done.
Accessibility hint describes the long press. No hardcoded test room/credentials.

Installed 1.0.16/code14 (`.tmp/Done-1.0.16-room-endpoint.apk`); release build
passed in1m14s, `.tmp/voice-1.0.16-room-endpoint-build.log`. Native audio behavior
otherwise matches1.0.15. Actual new picker still needs visual inspection.
Phone is now securely locked: window policy showing=true,secure=true,mTrusted=false,
screen awake but screenshots black. Requested user unlock through async input.
Did not bypass lock, start call, or change Bluetooth. Planned test is dedicated
room Atom call, then temporary Bluetooth off/on with original enabled state
restored, inspect same peer/session and native PCM queue counters. Do not infer
phone/Atom success from the prior PC protocol-only test. Both devices are ready
apart from the phone screen unlock.

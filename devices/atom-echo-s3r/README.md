# Atom Echo S3R voice prototype

Windows PC + Atom Echo S3R C126-ECHO + ATOMIC Battery Base. The Atom joins the
router on 2.4 GHz. The PC runs the local bridge and Dan browser voice session;
the battery powers the Atom when USB is removed. This is not a standalone
cloud-connected assistant. Wake phrase detection runs offline on this PC.

## Verified baseline

Custom ES8311/I2S firmware fixed the original quiet USB speaker. DAC gain is
0 dB (`0x32=BF`); browser output uses a 180 Hz highpass, gain 2 and peak limiter.
Analog microphone PGA is +18 dB (`0x14=16`). The user confirmed improved pickup
distance and battery-powered Wi-Fi conversations. 1 m recognition is not yet
verified. Raw ADC counters expose clipping; CDC `u/v/w/x` selects +12/+18/+24/0
dB temporarily, `?` reads diagnostics, and `z` clears counters.

## Interruption implementation

Authenticated `DAN4` TCP clients enable continuous microphone capture during
playback while conversation is ON and the host session is ready. Older protocols
are rejected; firmware and bridge must be updated together. The local bridge
uses WebRTC AEC3 through `pywebrtc-audio==0.2.0` to remove the speaker reference
and applies modest noise suppression. The device's 10 ms microphone packets
pace speaker output, bounding the host output queue to 60 ms.

The paired browser session uses semantic VAD with `eagerness: high` and
`interrupt_response: true`. On speech-start it clears local queued output and
mutes the worklet until the next response. Prompts request one or two sentences
per turn, except when a detailed answer is requested. This is interruption of
spoken output; it does not cancel a task already delegated to Dan.

Synthetic tests measured 17.5 dB echo attenuation while preserving an independent
near-end signal (RMS ratio .94). An 18-second real-device playback test measured
12.8 dB raw-to-processed attenuation and zero clipped samples. The duplex firmware
was flashed with hash verification; browser session readback confirmed semantic
VAD high, automatic interruption enabled and the short-turn prompt. The user
subsequently confirmed that spoken interruption stops Dan and normal conversation
works. The dedicated headless session was paired and verified connected, with
speech-start/output-clear events observed. Longer-term reliability, distance,
noise and battery tests remain; these checks do not establish production quality.

Prioritized remaining work and acceptance criteria: [TASKS.md](TASKS.md).

## Run on this PC

Install Python dependencies in an isolated environment using `requirements.txt`.
For the existing local setup, AEC packages are under `.tmp/atom-aec-tools`.
`start-wifi.ps1` starts the bridge, isolated Next frontend on port 3002, and
headless voice controller on 48802. It never opens or focuses a visible browser.
Install the dedicated Chromium binary with `python -m playwright install chromium`.
Normal production frontend port 3000 is not restarted.

First use: in your already-paired Chrome profile, open
`http://localhost:3002/atom-voice` and click the background-connect button.
This passes only the Dan login to the local controller, which verifies access
to the test room before saving it under `.tmp/atom-headless-auth.json`.
The controller does not read or attach to the user's Chrome profile, use the
clipboard, or send OS keyboard/mouse events. Its separate profile lives under
`.tmp/atom-headless-profile`; never commit either private location.
You can close the pairing page after connecting. The same page has a stop button.
If the login expires, pair again. The headless controller reports status/events
on `http://127.0.0.1:48802/status`; commands require the device pairing key.
It retries failed connections up to three times with backoff. A new button
intent or device reconnection resets the attempt limit. Authenticated `reconnect`
retries the current intent; it does not turn an OFF device ON.

## Wake phrase and conversational standby (DAN4)

The DAN4 firmware was flashed and its hash verified. Python tests, worklet tests
and TypeScript checks pass. Physical button/chime and user wake recognition
verification remain pending; do not claim reliable distance or noise performance.
An actual connected session accepted the test utterance "今日はここまで、また呼ぶね",
called the standby tool and returned the device to standby with the browser
connection closed. Standby diagnostics confirmed local wake PCM remained active
while cloud microphone output was zero.

Cold boot starts in standby. Say "Hey Dan", wait for the ready chime, then speak.
To finish, use natural language such as "今日はここまで、また呼ぶね". The model
calls `enter_voice_standby` based on intent. A temporary pause, thanks alone,
negated or quoted instructions, or stopping a project task should not close
the voice conversation. Standby does not issue a delegated-task cancellation.

The default wake phrase is configurable through private `wake_phrases` (English
phrases supported by the installed model). This is constrained offline speech
recognition, not a custom trained wake model. The wording for standby is not a
keyword list. Eight text intent cases passed against the actual Realtime model;
recognition of the user's voice and real conversational ambiguity still needs
physical testing. Synthetic English speech detected two "Hey Dan" samples and
rejected four other phrases; this small test does not establish a false-wake rate.

The existing button is a fallback. Short-press the built-in user
button (GPIO41, separate from the reset/download button) once to connect. A low
single tone acknowledges the request. Ready uses two soft notes G3-D4; standby
uses D4-G3. There is no third note or additional chord tone. Gentle detuning,
quiet overtones and a dark short reverberation preserve the approved warm sound.
Durations including the tail are 960/880 ms, with PCM RMS around 4500 and peak
below 18000. `preview_signature_cues.py --firmware-header` renders both the preview
and flash-resident 16 kHz PCM in `firmware/src/cue_sound.h`; the device interpolates
to 48 kHz. This uses 68,480 bytes including the short connection-request cue,
without expensive live synthesis. Speech gain is unchanged. There is no
normal status RGB LED on this model. Pairing explicitly requests ON; the pairing
page's Stop button requests OFF. Power cycling returns to standby.

Standby closes the headless voice session. With `wake_enabled: true`, microphone
PCM reaches the PC's offline Vosk detector over the authenticated LAN connection;
the bridge sends only silence to any lingering browser connection. Wake audio
and recognized text are neither saved nor sent to the cloud. When wake detection
is disabled/unavailable, the device sends silence in standby. The ADC and Wi-Fi
stay powered; this is not a physical microphone disconnect or battery-saving
sleep. Power OFF is required to disable all listening in this prototype.
USB serves power/provisioning;
USB audio streaming is disabled in this Wi-Fi firmware. Speaking interruption
remains available throughout an ON conversation.

Every 10 ms DAN4 frame has a 12-byte little-endian header (flags, boot nonce,
intent revision) and 960 bytes of 48 kHz mono PCM. Device flag 1 requests ON.
Host flag 1 acknowledges session readiness; 8 authorizes local wake capture in
standby. Flags 2/4 request OFF/ON, accepted only
for the matching boot/revision so stale commands cannot undo a later button
press. Readiness expires after one second without host frames; the bridge's
session lease expires after two seconds without the controller. Connection setup
frames carry silence. Reconnection preserves standby, and active sessions
need a fresh readiness lease before microphone audio resumes.

`voice_state.py` and bridge/controller tests cover standby, stale commands,
lease expiration, reconnection and cancellation of stalled startup on OFF.
Connection, intent, speech detection and output-stop events are retained in
`.tmp/atom-logs/bridge.jsonl` and `voice.jsonl` (1 MB each plus three rotations).
These logs contain metadata only; they do not store audio, transcripts or keys.

Wake setup: install `vosk==0.3.45` (this PC uses `.tmp/atom-wake-tools`) and extract
[vosk-model-small-en-us-0.15](https://alphacephei.com/vosk/models) under
`.tmp/atom-wake-models/`. The model is Apache-2.0 licensed. Set `wake_enabled: true`
and `wake_phrases: ["hey dan"]` in the private pairing config, then restart the
bridge. Recognition runs on a bounded worker queue with a three-second cooldown
after standby. Device-only wake detection and a purpose-trained "Hey Dan" model
remain future work. The PC must stay awake for this version to hear a wake phrase.

Private pairing config defaults to `.tmp/atom-wifi-pairing.json`; override with
`DAN_ATOM_CONFIG`. JSON keys are `ip` and `key` (32 random hex characters).
Never commit this file, router credentials, or original flash backups.
Device credentials/key are saved in NVS and survive restart. DHCP address
changes currently require updating the private config. Automatic discovery is
not implemented. `provision_wifi.py --ssid YOUR_ROUTER` reads only that Windows
saved network profile into memory and provisions over USB without printing its
password. Provision only a network you intend the Atom to join.

This prototype is locked to the dedicated voice-test room ID in `wifi_bridge.py`
and paired browser localStorage `dan-atom-wifi` (enabled, roomId, key). The project
URL is in the launcher. Other rooms are rejected. The bridge binds only to
127.0.0.1:48801, validates Origin/key/room, and accepts one browser at a time.
The Atom listens on LAN TCP 48800. This LAN transport is authenticated but not
encrypted; do not port-forward it or use it on an untrusted network.

Leave the PC awake and the background services running. To use the battery,
unplug USB, attach the base and move its switch ON. To reconnect USB for flash,
switch the base OFF and remove it first. Red LEDs show battery level. Firmware
download is a separate operation; normal battery use needs no boot button press.

## Build and diagnostics

`firmware/` uses PlatformIO espressif32@6.11.0 and ESP-IDF 5.4.1.
Run `python -m platformio run --project-dir devices/atom-echo-s3r/firmware` in
an ESP-IDF-compatible Python environment. Main task stack must be 8192 bytes.
Local modified `usb_device_uac` sources retain upstream license notices.
Generated build and managed-component directories are ignored.

Verified device MAC: b4:3a:45:bc:c0:20. Application USB is COM7 on this PC.
CDC `b` enters ROM download (COM8). Flash the application at 0x10000 with
esptool `--after watchdog-reset`; partitions/bootloader must match the existing
8 MB layout. Never target COM3 (the separate MOTU interface). Full original
8 MB backup is retained locally outside Git. Diagnostic speech was replaced by
generated chimes; the DAN4 build uses about 81% of the 1 MB app partition.
CDC `T` toggles conversation intent for automated device tests; `N` reports
requested/ready/boot/revision. Commands `1/2/3` play ready/stop/waiting chimes.
Wi-Fi speaker writes yield while a cue requests the shared
I2S output, preventing repeated high-priority writes from starving the cue.
CDC `?` gains `CUES` started/completed counters (ready, standby, request), write
errors and maximum lock wait. The update was flashed with hash verification.
An actual voice connection and semantic standby each completed their cue;
diagnostics reported zero write errors and a maximum lock wait of 8 ms.
Audibility remains a user check; write completion alone cannot establish how
loud the normal state-transition cues sound to the listener.
The user subsequently reported inaudible cues. A harmonic-enriched PCM revision
was flashed while retaining the two notes; audibility is still unconfirmed.
Standby now waits for both generation and actual playback to finish plus a
300 ms output tail. New user speech cancels pending standby; a drain timeout
keeps the session open. Six tests in `test_standby_drain.cjs` cover these cases.
A real session confirmed playback-ended before session-closed, fixing the earlier
cutoff of a spoken sign-off when the function call arrived before playback ended.

`GET http://127.0.0.1:48801/status` reports connection counts/timestamps,
raw/processed microphone RMS, speaker RMS and local interrupt flush count.
These are diagnostics, not audio recordings. `check_mic.py` records level and
clipping counters without storing audio. Historical errors can remain in status
after reconnect; inspect `device_connected` and timestamps together.

Checks: `python devices/atom-echo-s3r/test_audio_processing.py`,
`python -m unittest discover -s devices/atom-echo-s3r -p "test_*.py"`,
`node devices/atom-echo-s3r/test_worklet.cjs`, frontend `npx tsc --noEmit`,
firmware build/hash verification, then real-room echo and interruption tests.

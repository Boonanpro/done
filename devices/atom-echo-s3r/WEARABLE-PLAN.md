# Wearable Dan planning — 2026-09-12

## Confirmed feedback

The louder two-note firmware was flashed with hash verification. The user heard
both ready and standby cues and approved their volume. Keep this sound setting.
Conversation testing failed with `Not authenticated`; direct USB cue playback
succeeded. The saved controller credential contains an access token only.

## Target experience

- Two equivalent wearable units and a battery-powered, two-bay charging case.
- Wear one while the other charges; removing a replacement resumes the same
  Dan conversation without signing in or selecting a room again.
- Local wake phrase, natural-intent standby, interruptible speech, and optional
  Bluetooth headset conversation. Support home and outdoor use.
- Keep a command-center conversation independent of project rooms. Resolve
  ambiguous project references before dispatch; test only in the existing
  voice-device test room.

## Recommended architecture to validate

Wearable microphone/speaker -> Galaxy S25 native companion -> authenticated Dan
gateway -> project/task execution. Headsets pair with the phone. A server stores
conversation and task state; a single active-device lease avoids duplicate
commands during a swap. Charging insertion releases the microphone lease.

Use the existing Atom over phone Wi-Fi tethering for an initial outdoor trial.
This needs a phone-side bridge or a reachable authenticated gateway: tethering
alone does not replace the current PC bridge. For smaller, longer-running units,
evaluate a low-power Bluetooth audio transport and on-device wake detection.
Do not assume ESP32-S3 BLE implements standard headset audio profiles.

Automatic credential refresh, device provisioning/revocation, bounded reconnect,
process restart recovery and OTA updates are required. Keeping wake readiness
does not require a continuously open cloud audio session. Android screen-off,
restart, headset routing and competing phone calls need actual S25 tests.

## Hardware and battery gates

LARK M2 provides a useful two-transmitter/charging-case reference but does not
provide a speaker endpoint for Dan. Omi developer hardware is a candidate for
evaluation; verify exact purchasable revision, arbitrary audio playback,
simultaneous capture/playback and case compatibility before buying. NotePin's
recording workflow does not establish an arbitrary live duplex interface.

First measure idle/wake/listening/speaking currents and charge time. Proposed
targets (not measured): 4–6 hours mixed use per unit, recharge faster than the
other unit's runtime, a case with enough energy for a full waking day. Size and
capacity remain undecided. Case requires per-unit charging management,
protection, temperature handling and reliable pogo contacts, not only a shell.

Print wearable fit dummies, then working enclosures, then a two-bay case. Home
FDM printing is useful for fit iterations; PCB fabrication/assembly still needs
separate tools or a board vendor. Select the electronic stack before final CAD.

## References checked

- https://www.hollyland.com/product/lark-m2
- https://help.omi.me/en/articles/13149771-omi-devkit
- https://docs.omi.me/docs/developer/Protocol
- https://support.plaud.ai/hc/en-us/articles/54643893661977-Does-Plaud-support-real-time-transcription
- https://developer.android.com/develop/connectivity/bluetooth/ble/background
- https://developer.android.com/develop/background-work/services/fgs/service-types
- https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-guides/bt-architecture/overview.html

# Phone-only silence investigation — 2026-09-17

The user prioritized ordinary smartphone conversation over Atom integration.
Atom's PC bridge was stopped after unwanted wake activation; do not start it
or physical calls without explaining the test. Avoid unnecessary paid trials.

## Observed incident (JST)

Installed app 1.0.21/code 19, call 16:24:24–16:25:40, peer 0.
The user heard the greeting but no replies. Saved room transcripts contain
“あのさ”, “聞こえる”, and repeated “聞こえてる”/“おい”; the only assistant
transcript is “もしもし”. Thus capture and upstream recognition worked.

Phone log: native endpoint `phone`, `external=false`, format errors and queue
contention zero. Inbound packet loss zero throughout sampled records. Output
audio level after greeting stays approximately 0.0000305 while packets continue.
Only `session.started` appears among the previously logged lifecycle/error/
delegation events. No backend delegation or logged error explains the silence.
Call service was no longer active at inspection. Do not attribute this incident
to a disconnected Atom or assume the model simply failed to hear the user.

Evidence: `.tmp/phone-silence-logcat.txt` and saved room transcripts. Logs lack
outgoing context updates and their acknowledgments, so root cause is unresolved.

## Bounded isolation test

`.tmp/probe-mobile-silence.py`: one physically muted, isolated Live session,
cached synthetic speech, the same room history cutoff before the incident,
opening greeting instructions, two ordinary questions. Both received replies.
No room writes or physical device activation. This does not reproduce phone
acoustics or prove the incident fixed. Result:
`.tmp/voice-conversation-trial/mobile-silence-current-history.json`.

## Diagnostic change

1.0.22/code 20 logs outgoing control type/ID/length, append acknowledgments,
greeting milestones, and start of each input/output transcript segment.
No transcript text, microphone recording, or credentials added to diagnostic
logs. No automatic reconnect, response trigger, or new paid retry introduced.
18 mobile integration checks passed; release build passed. Installation and
the next physical conversation must be verified separately.

## Delivered follow-up

1.0.23/code 21 installed and package version verified. Adds phone-call speaker
toggle alongside mute/end. Uses InCallManager's existing route selection and
route-change notifications; speaker off prefers available Bluetooth, wired
headset, then earpiece. Visual state follows reported route, not optimistic
selection. Does not restart the Live session. Physical route/UI acceptance is
pending user test. Mobile typecheck, 18 integration checks and release build pass.

The reported text-chat OAuth failure is separately confirmed: Done resolved to
`fable`/Claude (no room-specific model); Claude auth reports not logged in.
Changed only Done through the normal Core room-model endpoint to
`gpt-6-astra`/Codex, respecting its active-turn guard. Codex authenticated
one-shot response returned OK. Did not replay failed user requests. Since the
silent voice call made no backend delegation, this authentication failure is
not established as the cause of voice silence.

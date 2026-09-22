# Android voice network investigation — 2026-09-20

Status: diagnostic update deployed and verified on phone; travel audio fault not resolved or reproduced at its reported severity.

Previous incident (September 19, 08:11–08:14 JST): installed update 01a0b10f-cff8-7a27-b7e4-038138f30ca6. ICE disconnected at 08:12:10. Receiver later reported 422 lost packets and 277 ms jitter, then recovered. Separately the weekly schedule question took approximately 74 seconds. Do not attribute that whole wait to packet loss without tracing the job/history response.

Phone audio uses direct WebRTC to OpenAI. The home server handles session establishment and work. Native phone mode bypasses the Atom PCM queues. Moving Core to cloud has not been established as a remedy for direct audio loss.

Added allowlisted selected ICE pair, remote inbound sender-loss, and decoder concealment statistics to mobile voice-health. Addresses, ports and candidate IDs are not persisted by this addition. Missing metrics stay null. Three quality tests and mobile TypeScript checks passed.

Android preview OTA 01a0bbd7-02a3-7850-9862-c958dc3f1610 (runtime 1.0.25) was published and its update ID verified in actual phone telemetry.

Two real Done-room calls received synthetic speech requesting a short story. Wi-Fi was disabled for 12 seconds then restored while the call remained active. The first earlier attempt did not connect and is not counted. No acoustic output recording was made, so these trials establish transport behavior and transcripts, not perceived intelligibility.

On the diagnostic call, selected protocol was UDP and Android reported networkType vpn. Before switching, RTT was 126 ms and upstream/downstream loss counters were zero. During switching, remote inbound reported 77 missing outgoing packets (fractionLost 0.617 for its reporting interval); receiver packetsLost remained zero but concealment increased. After switching, upstream loss stopped increasing, interval fractionLost returned to zero, RTT was 117 ms, and the same call continued. This is not evidence that steady poor-network operation is fixed.

The phone VPN is an existing local filtering service with split DNS routes; its presence alone does not establish that voice traffic is remotely tunneled or that it caused the incident. It was not disabled or changed.

Evidence: .tmp/voice-network-20260920/{health.json,messages.json,diagnostic-connected.json,diagnostic-connected-native.log,ota.json,quality-tests.log}. Test messages were reviewed and only eight exact synthetic message IDs were removed; cleanup.json records them. Wi-Fi restored enabled. Test calls ended; no Core restart performed.

Remaining: establish whether travel failure occurred on Wi-Fi or cellular; reproduce sustained loss on that route, compare an actual ChatGPT call under equivalent conditions, trace the separate slow schedule lookup, then validate any transport/dispatch fix against those failures. Do not claim a network fix from telemetry-only changes.

## Follow-up: user confirmed both networks

The user confirmed the travel fault occurred on both Wi-Fi and mobile data. A fault exclusive to that Wi-Fi is therefore not an adequate explanation.

An additional actual phone comparison was recorded on the current home Wi-Fi: Dan at 07:50 and ChatGPT at 07:53, using the same cached synthetic request for an official-source 24-hour McDonald's in Amagasaki. Both identified the Route 2 Amagasaki store. Dan's 15-second observations showed zero upstream/downstream packet loss and approximately 111–112 ms RTT. Its first delivered result at 22:50:44.110 UTC preceded assistant speech-start at 22:50:44.713 by 603 ms. This is result-to-speech telemetry, not full question-to-answer latency. It does not reproduce the travel loss or the previously reported long silence.

External microphone WAV recordings and periodic screenshots are in .tmp/phone-app-comparison/network-wifi-{dan,chatgpt}*. These have not yet been acoustically graded; do not claim naturalness, intelligibility or a precise ChatGPT latency advantage from transcripts alone. Dan's final maintenance-date transcript was malformed and needs comparison with the recording/source before attributing it to spoken output.

Native code also shows hardware AEC/NS disabled on all routes in DanExternalAudio.createDeviceModule, originally for Atom injection. Software processing on a phone route is a comparison candidate, not an established defect. No DSP setting was changed.

Both calls ended. Five exact Dan test messages were archived, reviewed and deleted (comparison-cleanup.json). The newly created ChatGPT test conversation titled '公式サイトで店舗検索' was deleted; screenshot chatgpt-cleaned.png confirms deletion. No unrelated history was removed.

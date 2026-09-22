# Voice delegation and timeline isolation repair

## Incident

Room a588ca6f-95b1-484a-a13d-cf7771ebffb8, timeline b864e235-6611-4d8d-b8e9-4d56e9226b5a.
At 20:56 JST the voice promised a storyboard; no backend-start followed that delegation.
At 21:00:54 status returned zero active jobs. Production was finally submitted at 21:01:02.
The session also opened with an unrelated old 30-second video's completion announcement.

## Repairs

- Persist conversation by room AND timeline. Legacy room history is restored only to its recorded timeline. Keep the active conversation's editing target while browsing reference timelines.
- Scope delayed speech/results/notifications by timeline as well as room.
- Transcript revisions invalidate speculative library ranking, not the outstanding delegation. Continue to Astra with updated original conversation.
- An empty library result continues to the backend instead of ending the request.
- Show the lookup stage beneath the orb, clear it after fast actions, and deliver execution-state changes silently to voice as thinking context.
- Clarify voice delegation vs actual execution. Encourage visual comparisons during ambiguous creative discussion; remove the backend restriction requiring another explicit request before external reference search.

## Verification and deployment

- 23 JavaScript tests pass, including updated transcript during lookup, empty library, wrong-timeline reports, live reference browsing, microphone pause and partial results.
- 6 Python Live configuration/response tests pass.
- Production-served browser check passes: no legacy A history in B; reopen A/B restores each; status line visible. Evidence: scratch/editor-conversation-fix/browser.json and presence.png.
- Production worker finished at 21:08:27 JST; safe restart initially refused while job active and was not forced. After completion and no active Core sessions, Sandbox restarted healthy on port 8000 (PID 35680). Core left running.
- No paid voice session created for this repair. Full natural voice behavior and subjective proposal quality remain unverified; deterministic regression checks do not establish those.

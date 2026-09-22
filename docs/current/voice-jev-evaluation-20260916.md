# Jev voice evaluation — 2026-09-16

Status (2026-09-17): user-provided key stored encrypted as `typesafe`; real API evaluation completed on `jev-1.13.0`. Live voice behavior has not been switched to Jev. See results below.

## Scope

Jev is evaluated as a decision component receiving a bounded conversation and current task state. It does not generate speech, run tools, approve purchases, or repair browser connections. Tests remain outside the live request path. No additional model is made a prerequisite for conversation.

`scripts/voice_jev_eval.py` calls the documented HTTP API with three independent Choice questions: speech handling, task handling, and whether a pending notice merits speech. A question and a request to stop speaking do not automatically stop work. Labels never enter model input. The 26 Japanese scenarios in `tests/fixtures/voice_jev_cases.json` are authored expectations inspired by observed failures, anonymized and without account/payment details. They are development examples, not an independent holdout or proof of Japanese accuracy. Ambiguous outcomes must be reviewed before setting operational thresholds.

Results retain probabilities, confidence, model identifier, token usage, matching expected labels, latency, and unavailable counts. Non-200, timeouts, invalid distributions and malformed responses never dispatch anything. No automatic retry. Unavailable cases remain separate from successful-response p50/p95. Authentication/overload/rate-limit errors stop the batch. Secret values and upstream error bodies are omitted from results.

Credentials are loaded from the existing credential service under `typesafe`, type `api_key`, secret in the normalized password field. No key was found in that service or the checked local environment. Do not paste keys into logs or source.

```powershell
cd D:\done
python -m scripts.voice_jev_eval --prepare
python -m scripts.voice_jev_eval --user-id 2582a188-ff24-4a4f-b989-6063034d90b2
```

## Completed checks

- Seven transport/schema/privacy unit tests passed. These use simulated API responses and do not establish Jev quality.
- Real current Gemini voice baseline through the Atom PCM/frontend path, with isolated headless Chromium and simulated device I/O. Existing dedicated voice test room; intercepted transcript writes; no physical device control or real external job.
- Connection: 5.188 seconds; greeting produced speaker PCM.
- Synthesized user speech: 「ちょっと待って。今の説明はやめて。聞こえたって一言だけ言って。」 Response recorded: 「聞こえたよ。」
- Synthesized user speech: 「この電話を切ってください。」 Standby requested once, 9.219 seconds after the injected audio ended. HTTP/page errors: none.
- Baseline artifacts: `.tmp/voice-compare-gemini.json`, `.tmp/voice-compare-gemini.png`. This baseline measures neither Jev nor the physical microphone, acoustic echo cancellation, or speaker audibility.

## Next steps

1. Obtain TypeSafe API access/key and store it in the credential service.
2. Run the Japanese cases from this PC; inspect individual errors and confidence rather than assuming advertised latency/calibration applies here.
3. Add held-out variations and compare with the current decision path on the same state.
4. Only after this, evaluate decisions alongside synthetic audio transcripts without changing live behavior. A control trial follows only for functions with demonstrated value; speech pause, task cancellation and approval are distinct outcomes.

The existing 30-second request failure, missing tool result and browser timeout remain separate repair work. This evaluation does not mark them fixed.

Official references read:
- https://typesafe.ai/blog/introducing-system-one-models-and-jev
- https://docs.typesafe.ai/api.md
- https://docs.typesafe.ai/concepts/system-one
- https://docs.typesafe.ai/confidence

## Access request (2026-09-16)

At the user's request, submitted the official typesafe.ai waitlist using the configured primary Gmail address. The page displayed `Waitlist Joined`; screenshot: `.tmp/typesafe-waitlist-result.png`. No API key was issued and no payment was made.

Attempted console email authentication twice, including requesting and opening a fresh magic link within the same dedicated browser session. Both attempts reached `/redirect-error` with a generic login error. This does not establish that waitlist gating caused the login error. Authentication links were consumed in memory and were not logged or saved to source files.

API evaluation remains pending actual access. Existing production voice behavior was not changed by registration.

## Invitation confirmed (2026-09-17)

Read-only IMAP check confirmed `TypeSafe AI: Your account is ready`, received 2026-09-16 18:44:30 UTC (September 17 03:44 JST). Body invites account creation. This is distinct from the waitlist confirmation. No TypeSafe API key is stored yet; API execution has not been verified. Account sign-in is being retried using the existing dedicated headless browser profile, without changing the user's browser.

Fresh email-link authentication in one browser context again reached `/redirect-error` (Login Error). The invite's Create your account link redirects to the same console `/login`; it did not expose a separate invitation onboarding route. No API key acquired, payment made, or support message sent.

## API registration and real evaluation (2026-09-17)

The user supplied an API key. Stored using CredentialsService under service `typesafe`, type `api_key`; key is not in source, result files, or this document. Real API requests succeeded and resolved to `jev-1.13.0`. The temporary local registration form was stopped after saving. No credential was added under `typesafe_jev`, which would enable the separately developed editor runtime; this assessment does not deploy a live control path.

First API batch exposed corrupt fixture inputs: Japanese text had been replaced with question marks. Those results are invalid as a quality assessment. Re-authored 26 Japanese development scenarios matching the existing intended categories; corrected one compound-stop utterance to express speech pause and work pause, consistent with its pre-existing labels. Added an encoding-loss rejection before API execution and fixture integrity coverage (9 unit tests passed). These re-authored cases are not recovered verbatim originals, private conversation logs, or a held-out benchmark.

Final real run: 26/26 successful responses, 21/26 cases matched all three expected dimensions, median 219ms, p95 296ms, max 531ms. Artifact: `.tmp/voice-jev-results-20260917-final.json`. Questions and decision criteria were unchanged during these runs.

Remaining mismatches include treating an end-call request as cancelling work, treating a question/quotation about ending a call as an actual end request, interpreting an ambiguous stop too decisively, and failing to classify an explicit purchase hold as a work pause. Therefore the current configuration should not directly control call termination, task cancellation, or purchase authorization. Fast candidate decisions are promising, but confidence thresholds and held-out wording/context need evaluation before live integration. No physical audio test was run; Atom is off and the headset is charging.

## Additional wording comparison

Ran 12 newly authored variants (ability questions, hypotheticals, reported past instructions, direct end, explanation pause, purchase hold, cancellation, negation, change, progress, combined pause). This is still a small development set, not an independent production-quality estimate. Original instructions matched all dimensions in 8/12. Replacing the speech/task instructions with shorter explicit separation of current intent versus questions/quotations and call versus work matched 10/12: one remaining reported-past end-call misclassification (speech confidence .32), one unavailable response rejected by transport/schema validation. Successful-response median235ms, p95375ms. No retries or production prompt changes. Results `.tmp/jev-control-comparison.json`, reproducible scratch runner `.tmp/jev-control-comparison.py`.

The result supports further evaluation, not live termination/cancellation authority. Do not count the unavailable case as success or tune a confidence threshold solely on these examples.

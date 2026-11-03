---
name: goal-test
description: "How Dan proves that a change to Dan (a call, a chat behavior, a screen, a tool) works for the owner before saying it is done: success decided from the owner's goal, a check that is first shown to fail on the known-bad case, the feature driven the way the owner uses it (a reacting partner for conversations), a second case the fix was not made from, and a pass/fail read from facts. Use it whenever you fix or build something in Dan and are about to test it, plan how to test it, or report that it works — especially voice calls (scripts/voice_goal_call.py), conversations, and anything the owner reported as broken — even when nobody says the word test."
---

# Testing from the owner's goal

The owner refused a check that replayed a failed call word for word and timed it (2026-11-03). In that call the owner had said 「これ40kgじゃん」 only because Dan showed a 40 kg set for 「100キロ」. Replayed after a fix, the owner side would complain about a page that is no longer there, and the numbers would say nothing about whether the owner can now buy a 100 kg set. A test is a claim about what the owner gets; build it from that.

The rules are in AGENTS.md ("Proving it works"). This skill is how to apply them.

## 1. Write down what success is, from the request

Before running anything, write one or two sentences of what the owner must end up with, in the owner's terms, and how a script can read it back:

- "The owner found a 95–125 kg barbell set that can be bought, shown on the call's screen" → read the shown page's title for the weight and its purchase button or schema.org availability.
- "「切って」 ends the call" → the call's own closed event, and seconds from the end of the owner's words.

Never derive the expected value from a run of the code. Prefer facts a script reads (a page's text, a saved row, a call's state) over a model's opinion of quality; where a model must read something (a photograph), let it copy text out, and apply your rules to what it copied.

## 2. Show the check can fail before trusting it can pass

Run the checker on a known-bad case first: the failure the owner reported, or the code before the fix. It must fail, for the right reason. Then run it on a known-good case; it must pass. Keep both as files next to the scenario (tests/voice_goals/known_bad_40kg.run.json and known_good_100kg.run.json are the pattern) so anyone can run them again.

If it passes the bad case, the check proves nothing; fix the check, not Dan.

## 3. Drive it the way the owner does

- **Conversation (a call, a chat)**: a partner that starts from the owner's goal and manner and reacts to what Dan actually said and showed. For calls this exists: `python scripts/voice_goal_call.py <screens> <scenario.json> <out>` (with `work.py try`: `http://127.0.0.1:3002`). The scenario (tests/voice_goals/*.json) holds the goal, the manner (what the owner says first, what they hold back), and the checks. The partner model only plays the owner; it never grades.
- **Screens**: open the real place and press what the owner presses (docs/places/README.md, `scripts/place_shot.py`).
- A recording of the failed conversation is good for exactly one thing: reproducing one bug such as a mishearing.

## 4. Suspect the observation first

When a run fails, check that the test saw what the owner sees before blaming Dan, and plan for it in every test, not only calls: the page did not finish loading, the test was sent to a login page or used another account, a read failed, a screenshot is older than the screen. Make the script stop with a separate result (exit 2, "the test could not see") instead of a fail, so a broken test is never reported as a broken Dan. On the first day the call test failed twice for its own reasons: the page stopped a shared microphone track, so the call heard silence; and a shop refused the test's plain browser while Dan's browser showed it fine, so the owner side complained of 「アクセス拒否」 the owner never saw. Signs: nothing of the owner was transcribed, the page read by the test differs from the photograph on the call's screen. voice_goal_call.py now stops with exit 2 when nothing it said reached the call, and the owner side sees the photograph of the call's screen.

## 5. Prove it generalizes with a case the fix was not made from

Fix with one scenario, then run another the fix never saw (tests/voice_goals/yoga_mat_10mm.json after weights_100kg.json). A conversation is not deterministic: run each scenario more than once and report the count ("2 of 3 passed"), not the best run.

## 6. Report

To the owner: what now works in their words, and what still does not, with the failing case named. Which cases were run, how many times, and which passed. Do not call an untested case working. Leave the run folders (run.json, grade.json, the screen photographs, voices.webm) where they can be opened again.

## Adding a call scenario

Copy tests/voice_goals/weights_100kg.json. Checks available in scripts/voice_goal_grade.py:

| kind | passes when |
|---|---|
| `pages` | every page shown on the call's screen has the number `pattern` finds in its title within `min`–`max`, and can be bought (`in_stock`); at least `at_least` shown |
| `shown_after_ask` | the first fitting page appeared within `max_s` of the owner's first request matching `ask` |
| `reply_gap` | after each thing the owner said, Dan's next words came within `max_s` |
| `hangup` | after the owner's first request to hang up, the call closed within `within_s` |

A new kind of goal needs a new check in voice_goal_grade.py, tested on a bad and a good run file before use.

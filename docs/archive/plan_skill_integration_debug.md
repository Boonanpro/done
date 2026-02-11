# Skill Integration Debug Plan (Root-Cause, Systemic)

## Goal
Fix recurring failures around generated skills so they behave like first?class skills and do not regress:
- Wrong routing (?hello? reply instead of skill lookup)
- Misclassification of generated skills (e.g., Amazon subgroup)
- Credential re?prompt despite stored credentials
- Tool result double?send errors
- Inconsistent skill listing and naming

## Non?Goals
- One?off hotfixes that do not generalize
- Manual ?per skill? patching without systemic rules

## Principles (Prevent Recurrence)
1. **Make routing deterministic** for skill?lookup intents.
2. **Normalize skill grouping** (domain/parent/alias) at load time.
3. **Unify credential lookup** by service group, not skill name.
4. **Guarantee tool_result uniqueness** at the transport layer.
5. **Auto?refresh skill registry** after generation.

---

## Phase 0 ? Evidence Collection (No Fixes Yet)
**Purpose:** Confirm the failure points before modifying logic.

- Capture a reproducible transcript for:
  - ?amazon_order_history????????
  - ??????????????
  - ????Amazon???????????
- Log:
  - State routing decision (intake/plan/process/answer)
  - Skill prompt injection payload
  - tool_use + tool_result IDs (detect duplicates)

**Exit criteria:** We can point to exact routing step + tool_result duplication site.

---

## Phase 1 ? Intent Routing Fix (Systemic)
**Root cause addressed:** skill?lookup intent falls into greeting/idle path.

**Plan**
- Add a deterministic branch for skill?lookup queries:
  - Example: ?X???/????, ??????????, ?Amazon????????
- Route these to a **SkillLookup** handler that:
  - Loads skill registry (fresh)
  - Uses grouping metadata (domain/parent)
  - Returns a structured answer

**Exit criteria:** ?amazon_order_history????? consistently returns skill info, not greeting.

---

## Phase 2 ? Skill Grouping & Listing (Systemic)
**Root cause addressed:** generated skills not classified as Amazon subgroup.

**Plan**
- Implement canonical **skill group** classification:
  - Use domain from SKILL.md (URL)
  - Allow optional `parent_skill` metadata (e.g., amazon)
- Update listing filter to use **group/domain**, not directory name.
- Ensure new skills populate group info immediately after generation.

**Exit criteria:** ?Amazon??????? includes amazon_order_history.

---

## Phase 3 ? Credential Reuse (Systemic)
**Root cause addressed:** credential lookup keyed by skill name ? misses stored creds.

**Plan**
- Introduce **credential service group** mapping:
  - Any Amazon sub?skill uses group = `amazon`
- Extend credential param extraction to include `email` explicitly.
- Store credentials under the group key (not per skill).

**Exit criteria:** After one input, Amazon credentials are reused by amazon_order_history with no re?prompt.

---

## Phase 4 ? Tool Result Uniqueness (Systemic)
**Root cause addressed:** duplicate tool_result blocks per tool_use ID.

**Plan**
- Add a dedupe guard at tool_result emitter:
  - One `tool_result` per `tool_use_id`
  - No retry re?emit with same ID
- Add logging to surface duplicates if attempted.

**Exit criteria:** No OpenAI 400 invalid_request_error for duplicate tool_result.

---

## Phase 5 ? Naming and Documentation Hygiene (Systemic)
**Root cause addressed:** inconsistent naming and docs not auto?updated.

**Plan**
- Standardize display name via SKILL.md title policy (simple names).
- Ensure generation post?hook refreshes skill registry + list.
- Ensure SKILL.md contains domain + actions table for parser.

**Exit criteria:** ?Amazon Skill v3 (Vision?based)? becomes ?Amazon Skill?, docs auto?updated.

---

## Verification Matrix
- Skill lookup returns correct info (no greeting fallback)
- Amazon skill filter includes generated sub?skills
- Credentials reused without re?prompt
- No duplicate tool_result errors
- Skill list updated immediately after generation

---

## Rollback / Safety
- All changes are additive + gated by tests/logs.
- If regression detected, revert specific phase in isolation.

---

## Deliverables
- Code changes per Phase 1?5
- Logged evidence in Phase 0
- Updated tests (where applicable)

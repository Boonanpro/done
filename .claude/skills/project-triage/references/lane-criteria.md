# Lane Criteria

Use this table when lane selection is unclear.

## Decision Table

| Signal | Lane |
| --- | --- |
| Secretary can complete quickly without business delegation | A0 |
| Implementation should be quality-first via business workers | A1 |
| Multiple steps/dependencies exist but stack fit is known | B |
| Feasibility, estimates, or go/no-go depends on current AI capability uncertainty | C |

## Escalation Heuristics

Promote to `B` when:
- 3+ major tasks must be coordinated
- External integration and internal changes must be sequenced
- User requests a plan before implementation

Promote to `A1` when:
- It is mostly implementation work and quality-first execution is preferred
- The user expects business-side execution even for moderate complexity

Promote to `C` when:
- Delivery promise depends on what AI can do today
- Cost/schedule/team estimate requires current market/tool evidence
- Conflicting or stale information likely changes the decision

## De-Escalation Heuristics

Downgrade from `C` to `B` if:
- Capability uncertainty is low after quick validation
- Major decisions do not depend on external capability shifts

Downgrade from `B` to `A0/A1` if:
- Steps collapse into a short linear implementation path

When downgrading from `B`, choose:
- `A0` for secretary-scope direct handling
- `A1` for business direct implementation

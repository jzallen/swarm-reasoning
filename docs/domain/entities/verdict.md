# Entity: Verdict

## Description

The final output of a run, containing a factuality score, rating label, narrative explanation, and an annotated citation list aggregating all sources used across all agents.

## Invariants

- **INV-1**: A verdict must have a factuality score in the range [0.0, 1.0].
- **INV-2**: A verdict must have a rating label mapped from the factuality score to the PolitiFact scale.
- **INV-3**: A verdict must include a citation list aggregating all source URLs from all agents.
- **INV-4**: A verdict can only be emitted after all Phase 2 agents have published a terminal status (`F` or `X`).
- **INV-5**: A verdict belongs to exactly one run.
- **INV-6**: A verdict is immutable once finalized.

## Value Objects

| Name | Type | Constraints |
|------|------|-------------|
| `FactualityScore` | decimal | Range [0.0, 1.0], precision to 2 decimal places |
| `RatingLabel` | Enum | `true` · `mostly-true` · `half-true` · `mostly-false` · `false` · `pants-on-fire` |
| `SignalCount` | integer | Number of distinct authoritative observations that fed into the verdict, >= 0 |

## Factuality Score → Rating Label Mapping

| Score Range | Rating Label |
|-------------|-------------|
| 0.90 – 1.00 | True |
| 0.70 – 0.89 | Mostly True |
| 0.45 – 0.69 | Half True |
| 0.25 – 0.44 | Mostly False |
| 0.10 – 0.24 | False |
| 0.00 – 0.09 | Pants on Fire |

## Creation Rules

- **Created by**: Synthesizer agent (publishes CONFIDENCE_SCORE, VERDICT, VERDICT_NARRATIVE observations)
- **Persisted by**: `FinalizeSessionUseCase` (reads synthesizer observations, aggregates citations, writes to PostgreSQL)
- **Requires**: factuality score, rating label, narrative, citation list, signal count
- **Generates**: verdict ID, finalized timestamp

## Aggregate Boundary

- **Root**: Verdict
- **Contains**: Citations (1:N)
- **References** (by ID): Run
- **Produces**: Static HTML snapshot (verdict view + chat progress view)

## Downstream Effects

When a verdict is finalized:
1. Citations are persisted to PostgreSQL
2. Static HTML snapshot is rendered (verdict + chat toggle)
3. Snapshot stored to S3 (or local filesystem in dev)
4. Final SSE event sent to frontend with verdict payload
5. Session transitions from `active` to `frozen`
6. SSE connection closed

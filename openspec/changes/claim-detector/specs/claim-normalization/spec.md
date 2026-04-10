# Capability: claim-normalization

## Purpose

Produce a canonical, normalized form of the submitted claim text suitable for downstream matching, retrieval, and scoring. Normalization removes epistemic hedges, lowercases the text, and resolves pronoun and demonstrative references where entity context is available.

Normalization runs before scoring (see design.md Decision 1). The normalized form is what the scorer, the entity-extractor, and all fanout agents operate on.

---

## Inputs

| Source | Field | Type | Description |
|---|---|---|---|
| Redis Stream `reasoning:{runId}:ingestion-agent` | `CLAIM_TEXT` | ST | Raw claim text as submitted |
| Redis Stream `reasoning:{runId}:ingestion-agent` | `ENTITY_PERSON` (0..N) | ST | Named persons if pre-published by ingestion-agent |
| Redis Stream `reasoning:{runId}:ingestion-agent` | `ENTITY_ORG` (0..N) | ST | Named organizations if pre-published |

Entity observations from the ingestion stream are used opportunistically: if present, they inform pronoun resolution. If absent, pronoun references are left unresolved (not guessed). The entity-extractor (separate agent in Phase 1) performs full NER after claim-detector; its output is not available to the normalizer.

---

## Output

### Observation: CLAIM_NORMALIZED

```json
{
  "type": "OBS",
  "observation": {
    "runId": "{runId}",
    "agent": "claim-detector",
    "seq": 1,
    "code": "CLAIM_NORMALIZED",
    "value": "biden issued a federal vaccine mandate for all private employers.",
    "valueType": "ST",
    "units": null,
    "referenceRange": null,
    "status": "F",
    "timestamp": "2026-04-10T12:00:02Z",
    "method": "normalize_claim",
    "note": null
  }
}
```

`CLAIM_NORMALIZED` is always emitted with `status = "F"`. Normalization is deterministic -- there is no preliminary hypothesis phase.

---

## Normalization Pipeline

The pipeline is applied in this order:

### Step 1 -- Lowercase

Convert the entire claim text to lowercase using Unicode-aware lowercasing (Python `str.casefold()`). Preserves punctuation and whitespace.

```
Input:  "Biden Said that HE Issued a Federal Vaccine Mandate"
Output: "biden said that he issued a federal vaccine mandate"
```

### Step 2 -- Hedging language removal

Remove or replace a fixed lexicon of epistemic hedging phrases. Matching is case-insensitive (applied after lowercasing) and uses whole-phrase boundary matching to avoid partial-word removal.

Hedging phrase lexicon (exhaustive list; no LLM inference):

| Pattern (regex) | Replacement |
|---|---|
| `\breportedly\b` | (remove) |
| `\ballegedly\b` | (remove) |
| `\bsources say\b` | (remove) |
| `\bsource[s]?\s+close\s+to\b` | (remove phrase through next noun) |
| `\baccording\s+to\s+sources\b` | (remove) |
| `\bsome\s+say\b` | (remove) |
| `\bit\s+is\s+claimed\s+that\b` | (remove) |
| `\bpurportedly\b` | (remove) |
| `\bapparently\b` | (remove) |
| `\bseemingly\b` | (remove) |
| `\bunconfirmed\s+reports\s+(say\|suggest\|indicate)\b` | (remove phrase) |

After removal, collapse multiple spaces to single space and strip leading/trailing whitespace.

```
Input:  "reportedly, biden allegedly issued a mandate"
Output: "biden issued a mandate"
```

### Step 3 -- Entity reference resolution (opportunistic)

If entity observations are available from the ingestion stream, replace first-person and demonstrative pronouns where the referent can be determined from context.

Resolution rules:
- If a single `ENTITY_PERSON` is present and the claim contains "he", "she", "they" (as a singular pronoun), replace with the canonical entity name.
- If a single `ENTITY_ORG` is present and the claim contains "it", "they" (as an organizational pronoun), replace with the canonical org name.
- If multiple persons or orgs are present, skip pronoun resolution (ambiguous referent).
- Demonstrative "the bill", "the act", "the policy", "the order" are not resolved (no source document parsing at this phase).

```
Input (entities: ["Biden"]):  "he issued a mandate requiring vaccination"
Output:                       "biden issued a mandate requiring vaccination"
```

If no entity observations are available in the ingestion stream:

```
Input:  "he issued a mandate"
Output: "he issued a mandate"    # pronouns left as-is; note added to observation
```

When pronoun resolution is skipped due to ambiguity or missing entities, the observation `note` field records: `"pronoun_resolution: skipped (no entity context)"`.

### Step 4 -- Whitespace normalization

Collapse all whitespace sequences (spaces, tabs, newlines) to a single ASCII space. Strip leading and trailing whitespace. Remove duplicate punctuation artifacts introduced by hedge removal (e.g., ", ," -> ",").

---

## Normalization Examples

| Raw input | Normalized output | Note |
|---|---|---|
| `"Biden issued a federal vaccine mandate for all private employers."` | `"biden issued a federal vaccine mandate for all private employers."` | Basic lowercase |
| `"Reportedly, the senator allegedly accepted bribes."` | `"the senator accepted bribes."` | Hedge removal |
| `"Sources say he increased unemployment by 5%."` | `"he increased unemployment by 5%."` (no entity) or `"donald trump increased unemployment by 5%."` (with ENTITY_PERSON=Donald Trump) | Conditional resolution |
| `"The unemployment rate is 3.7%."` | `"the unemployment rate is 3.7%."` | No hedges, no pronouns |
| `"It SEEMS that APPARENTLY the vaccine is safe."` | `"the vaccine is safe."` | Multiple hedges removed |

---

## Output Constraints

- `CLAIM_NORMALIZED` value must be <= 200 characters (ST type, per observation schema spec 3.2). If the normalized text exceeds 200 characters, truncate at the last word boundary before the limit and append `"..."`. Log a warning.
- Value must be non-empty. If normalization produces an empty string (e.g., the entire claim was hedging language), use the lowercased raw `CLAIM_TEXT` as a fallback and set `note = "normalization: fallback to raw text"`.

---

## Integration with Temporal Activity

Normalization is called internally by the `ClaimDetectorHandler.run()` method before scoring. It is not exposed as a standalone Temporal activity -- the handler calls `normalize_claim_text()` directly as a pure Python function within the `run_agent_activity` Temporal activity.

```python
def normalize_claim_text(
    raw_text: str,
    entity_persons: list[str] | None = None,
    entity_orgs: list[str] | None = None,
) -> NormalizeResult:
    """
    Returns:
        NormalizeResult with fields:
            normalized: str           # the normalized claim text
            hedges_removed: list[str] # list of phrases removed
            pronouns_resolved: bool   # True if any pronoun was resolved
            fallback_used: bool       # True if normalization produced empty string
    """
```

---

## Error Conditions

| Condition | Behavior |
|---|---|
| `CLAIM_TEXT` not found in ingestion stream | Raise `StreamNotFound`; activity retries via Temporal |
| Normalized text is empty after pipeline | Fall back to `casefold(raw_text)`; set `note = "normalization: fallback to raw text"` |
| Normalized text exceeds 200 chars | Truncate at word boundary + `"..."`; log warning |

---

## Gherkin Coverage

Scenarios in `docs/features/claim-ingestion.feature`:

- **"Claim detector publishes normalized claim text"** -- asserts F-status observation for `CLAIM_NORMALIZED`, value is lowercase, value does not contain "reportedly" or "allegedly"

---

## Test Scenarios

### Unit tests (`tests/unit/agents/test_normalizer.py`)

| Test | Input | Expected |
|---|---|---|
| Lowercase conversion | `"BIDEN SIGNED THE ORDER"` | `"biden signed the order"` |
| Remove "reportedly" | `"Reportedly, taxes increased."` | `"taxes increased."` |
| Remove "allegedly" | `"He allegedly fled the country."` | `"he fled the country."` |
| Remove "sources say" | `"Sources say the rate is 5%."` | `"the rate is 5%."` |
| Remove multiple hedges | `"Reportedly, allegedly, the senator lied."` | `"the senator lied."` |
| Pronoun resolution (single person) | `"he signed the bill"` + `entity_persons=["Biden"]` | `"biden signed the bill"` |
| Pronoun resolution (multiple persons) | `"he signed the bill"` + `entity_persons=["Biden", "Obama"]` | `"he signed the bill"` (skipped) |
| No entity context | `"he signed the bill"` + `entity_persons=None` | `"he signed the bill"` |
| Empty result fallback | `"reportedly allegedly"` | lowercased raw text |
| Text > 200 chars | 210-char normalized string | truncated at word boundary + "..." |
| Whitespace collapse | `"biden   signed   it"` | `"biden signed it"` |
| Punctuation artifact cleanup | `"biden ,  signed it"` | `"biden, signed it"` |
| Unicode casefold | `"STRASSE"` | `"strasse"` (German test) |

### Integration tests (`tests/integration/agents/test_claim_detector.py`)

| Test | Assertion |
|---|---|
| CLAIM_NORMALIZED published before CHECK_WORTHY_SCORE | seq(CLAIM_NORMALIZED) < seq(CHECK_WORTHY_SCORE) |
| CLAIM_NORMALIZED has status F | Observation status field = "F" |
| CLAIM_NORMALIZED value is lowercase | `value == value.lower()` |
| CLAIM_NORMALIZED does not contain hedging phrases | Value does not match hedging phrase regex |
| CLAIM_NORMALIZED method field | `method = "normalize_claim"` |

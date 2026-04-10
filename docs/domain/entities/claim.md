# Entity: Claim

## Description

A natural-language assertion submitted by a user for fact-checking. A claim is the input to the agent pipeline. It is immutable once submitted — the system evaluates the claim as given.

## Invariants

- **INV-1**: Claim text must be a non-empty string.
- **INV-2**: Claim text must not exceed 2000 characters.
- **INV-3**: Claim text is immutable after creation.
- **INV-4**: A claim belongs to exactly one session.

## Value Objects

| Name | Type | Constraints |
|------|------|-------------|
| `ClaimText` | string | Non-empty, max 2000 characters, trimmed of leading/trailing whitespace |
| `SourceUrl` | URL (optional) | The URL where the claim was originally published, if provided by the user |
| `SourceDate` | ISO 8601 date (optional) | Publication date of the original claim source |

## Creation Rules

- **Requires**: claim text
- **Optional**: source URL, source date
- **Generates**: submitted timestamp (UTC)
- **Validation**: Text is trimmed, checked for length, and rejected if empty after trimming

## Aggregate Boundary

- **Owned by**: Session (1:1)
- **Consumed by**: Ingestion agent (reads claim text to begin pipeline)

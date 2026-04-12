"""Scoring and confirmation prompt templates for check-worthiness evaluation."""

SCORING_PROMPT = """\
You are a fact-check worthiness evaluator. Assess the following claim and return \
a JSON object with two fields:
- "score": a float between 0.0 and 1.0 representing how check-worthy the claim is
- "rationale": a brief (1-2 sentence) explanation

Scoring criteria:
- Contains a specific, verifiable factual assertion → higher score
- Attributed to a named person, organization, or institution → higher score
- Contains measurable quantities, percentages, or dates → higher score
- Pure opinion, normative judgment, or satire → score approaches 0.0
- Non-falsifiable statement (e.g. "politicians are corrupt") → score approaches 0.0
- Hedging language (allegedly, reportedly, sources say) → lower score
- Metaphor, hyperbole, or rhetorical question → score approaches 0.0

Respond with ONLY the JSON object, no other text.

Claim: {claim_text}"""

CONFIRM_PROMPT = """\
You previously scored the following claim for check-worthiness and gave it {score}.

Claim: {claim_text}

Confirm or revise the score. Respond with ONLY a JSON object:
{{"score": <float 0.0-1.0>, "rationale": "<brief explanation>"}}"""

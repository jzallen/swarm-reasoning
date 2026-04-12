"""Verdict narrative generation: LLM-generated with fallback template."""

from __future__ import annotations

import asyncio
import json
import logging
import os

from swarm_reasoning.agents.synthesizer.models import ResolvedObservationSet

logger = logging.getLogger(__name__)

# Hard timeout for LLM narrative call
LLM_TIMEOUT_S = 5

# Length constraints
MIN_NARRATIVE_LENGTH = 200
MAX_NARRATIVE_LENGTH = 1000

_SYSTEM_PROMPT = (
    "You are a fact-checking verdict narrator. Your job is to explain a fact-checking "
    "verdict in plain, accurate language. Cite specific findings using [OBX-{seq}] "
    "notation. Reference source URLs with their validation status. Do not hedge unless "
    "the verdict is UNVERIFIABLE."
)


def _extract_cwe_code(cwe_value: str) -> str:
    """Extract the code portion from a CWE value."""
    return cwe_value.split("^")[0] if "^" in cwe_value else cwe_value


def _parse_citation_list(citation_text: str) -> list[dict]:
    """Parse CITATION_LIST value (JSON array of citation objects)."""
    try:
        citations = json.loads(citation_text)
        if isinstance(citations, list):
            return citations
    except (json.JSONDecodeError, TypeError):
        pass
    return []


class NarrativeGenerator:
    """Generate a human-readable verdict narrative."""

    async def generate(
        self,
        resolved: ResolvedObservationSet,
        verdict: str,
        confidence_score: float | None,
        override_reason: str,
        warnings: list[str],
        signal_count: int,
        citation_list: list[dict] | None = None,
    ) -> str:
        """Generate narrative via LLM with fallback to template."""
        if citation_list is None:
            citation_obs = resolved.find("CITATION_LIST")
            if citation_obs is not None:
                citation_list = _parse_citation_list(citation_obs.value)
            else:
                citation_list = []

        # Try LLM generation
        try:
            narrative = await asyncio.wait_for(
                self._llm_generate(
                    resolved,
                    verdict,
                    confidence_score,
                    override_reason,
                    warnings,
                    signal_count,
                    citation_list,
                ),
                timeout=LLM_TIMEOUT_S,
            )
            # Length validation
            if len(narrative) < MIN_NARRATIVE_LENGTH:
                # Retry once with explicit length instruction
                try:
                    narrative = await asyncio.wait_for(
                        self._llm_generate(
                            resolved,
                            verdict,
                            confidence_score,
                            override_reason,
                            warnings,
                            signal_count,
                            citation_list,
                            length_retry=True,
                        ),
                        timeout=LLM_TIMEOUT_S,
                    )
                except (asyncio.TimeoutError, Exception):
                    pass
            if len(narrative) < MIN_NARRATIVE_LENGTH:
                narrative = self._fallback_narrative(
                    resolved,
                    verdict,
                    confidence_score,
                    override_reason,
                    warnings,
                    signal_count,
                    citation_list,
                )
            elif len(narrative) > MAX_NARRATIVE_LENGTH:
                narrative = self._truncate(narrative)
            return narrative
        except (asyncio.TimeoutError, Exception):
            logger.warning("LLM narrative generation failed, using fallback")

        return self._fallback_narrative(
            resolved,
            verdict,
            confidence_score,
            override_reason,
            warnings,
            signal_count,
            citation_list,
        )

    async def _llm_generate(
        self,
        resolved: ResolvedObservationSet,
        verdict: str,
        confidence_score: float | None,
        override_reason: str,
        warnings: list[str],
        signal_count: int,
        citation_list: list[dict],
        length_retry: bool = False,
    ) -> str:
        """Call Anthropic API for narrative generation."""
        import anthropic

        prompt_parts: list[str] = []

        # Section 1: Verdict
        if confidence_score is not None:
            conf_str = f"{confidence_score:.2f}"
        else:
            conf_str = "insufficient evidence"
        prompt_parts.append(f"Verdict: {verdict} (confidence: {conf_str})")

        # Section 2: Key findings
        prompt_parts.append("\nKey findings:")
        sorted_obs = sorted(resolved.observations, key=lambda o: o.seq)
        for obs in sorted_obs:
            prompt_parts.append(f"[OBX-{obs.seq}] {obs.agent} / {obs.code}: {obs.value}")

        # Section 3: Source citations
        if citation_list:
            prompt_parts.append("\nSource citations:")
            for cit in citation_list:
                source_name = cit.get("sourceName", "Unknown")
                status = cit.get("validationStatus", "unknown")
                url = cit.get("sourceUrl", "")
                agent = cit.get("agent", "")
                prompt_parts.append(f"- {source_name} ({status}): {url} [cited by {agent}]")

        # Section 4: Override
        if override_reason:
            prompt_parts.append(f"\nClaimReview override was applied: {override_reason}")

        # Section 5: Warnings
        if warnings:
            prompt_parts.append(f"\nCoverage gaps: {'; '.join(warnings)}")

        # Section 6: Instructions
        instructions = [
            "\nInstructions:",
            "- Write 200-1000 characters",
            "- Cite at least 3 observations by [OBX-N] notation",
            "- Reference key source URLs with validation status "
            "(e.g., 'according to CDC (live source)')",
            "- Use plain language appropriate for a news reader",
        ]
        if verdict == "UNVERIFIABLE":
            instructions.append(
                "- Explain which signals were missing rather than stating a truth value"
            )
        if verdict == "PANTS_FIRE":
            instructions.append(
                "- Explicitly state the claim is false and cite contradicting evidence"
            )
        instructions.append("- Do not include any metadata or JSON")
        if length_retry:
            instructions.append(
                "- IMPORTANT: Your previous response was too short. Write at least 200 characters."
            )
        prompt_parts.extend(instructions)

        user_message = "\n".join(prompt_parts)

        client = anthropic.AsyncAnthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        )
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text.strip()

    def _fallback_narrative(
        self,
        resolved: ResolvedObservationSet,
        verdict: str,
        confidence_score: float | None,
        override_reason: str,
        warnings: list[str],
        signal_count: int,
        citation_list: list[dict],
    ) -> str:
        """Generate a template-based fallback narrative."""
        parts: list[str] = []
        parts.append(
            f"Verdict: {verdict}. This determination is based on "
            f"{signal_count} signals from upstream agents."
        )

        # Domain alignment
        alignment_obs = resolved.find("DOMAIN_EVIDENCE_ALIGNMENT")
        if alignment_obs:
            code = _extract_cwe_code(alignment_obs.value).lower()
            parts.append(f" Domain evidence {code}s the claim.")
        else:
            parts.append(" Domain evidence was absent.")

        # ClaimReview
        cr_match = resolved.find("CLAIMREVIEW_MATCH")
        if cr_match and _extract_cwe_code(cr_match.value) == "TRUE":
            cr_verdict = resolved.find("CLAIMREVIEW_VERDICT")
            if cr_verdict:
                cr_code = _extract_cwe_code(cr_verdict.value)
                parts.append(f" An external fact-check rated this claim {cr_code}.")

        # Corroboration
        corr_obs = resolved.find("CROSS_SPECTRUM_CORROBORATION")
        if corr_obs:
            corr_code = _extract_cwe_code(corr_obs.value)
            parts.append(f" Cross-spectrum corroboration was {corr_code}.")
        else:
            parts.append(" Cross-spectrum corroboration was absent.")

        # Source convergence
        conv_obs = resolved.find("SOURCE_CONVERGENCE_SCORE")
        if conv_obs:
            try:
                conv_val = float(conv_obs.value)
                parts.append(f" Source convergence score: {conv_val:.2f}.")
            except (ValueError, TypeError):
                pass

        # Citations summary
        if citation_list:
            live_count = sum(1 for c in citation_list if c.get("validationStatus") == "live")
            dead_count = sum(1 for c in citation_list if c.get("validationStatus") == "dead")
            parts.append(
                f" Sources: {len(citation_list)} citations, {live_count} live, {dead_count} dead."
            )

        # Warnings
        if warnings:
            parts.append(" Note: some upstream signals were incomplete.")

        narrative = "".join(parts)

        # Pad if too short
        if len(narrative) < MIN_NARRATIVE_LENGTH:
            narrative += (
                f" The analysis evaluated evidence from {signal_count} distinct "
                "observations across multiple verification agents to reach this "
                "determination. Each signal was weighted according to its source "
                "reliability and cross-referenced against independent sources."
            )

        # Truncate if too long
        if len(narrative) > MAX_NARRATIVE_LENGTH:
            narrative = self._truncate(narrative)

        return narrative

    def _truncate(self, text: str) -> str:
        """Truncate at the last complete sentence before MAX_NARRATIVE_LENGTH."""
        if len(text) <= MAX_NARRATIVE_LENGTH:
            return text
        truncated = text[:MAX_NARRATIVE_LENGTH]
        # Find last sentence-ending punctuation
        for i in range(len(truncated) - 1, -1, -1):
            if truncated[i] in ".!?":
                return truncated[: i + 1]
        # No sentence boundary found, hard truncate
        return truncated

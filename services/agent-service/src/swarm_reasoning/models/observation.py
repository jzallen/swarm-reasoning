"""Observation model and OBX code registry (ADR-011)."""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, model_validator


class ValueType(str, Enum):
    """Observation value type discriminators."""

    ST = "ST"  # Short string, <= 200 chars
    NM = "NM"  # Numeric, parseable as float
    CWE = "CWE"  # Coded value: CODE^Display^CodingSystem
    TX = "TX"  # Long text, > 200 chars


class ObservationCode(str, Enum):
    """All 36 observation codes from obx-code-registry.json."""

    # ingestion-agent
    CLAIM_TEXT = "CLAIM_TEXT"
    CLAIM_SOURCE_URL = "CLAIM_SOURCE_URL"
    CLAIM_SOURCE_DATE = "CLAIM_SOURCE_DATE"
    CLAIM_DOMAIN = "CLAIM_DOMAIN"

    # claim-detector
    CHECK_WORTHY_SCORE = "CHECK_WORTHY_SCORE"
    CLAIM_NORMALIZED = "CLAIM_NORMALIZED"

    # entity-extractor
    ENTITY_PERSON = "ENTITY_PERSON"
    ENTITY_ORG = "ENTITY_ORG"
    ENTITY_DATE = "ENTITY_DATE"
    ENTITY_LOCATION = "ENTITY_LOCATION"
    ENTITY_STATISTIC = "ENTITY_STATISTIC"

    # claimreview-matcher
    CLAIMREVIEW_MATCH = "CLAIMREVIEW_MATCH"
    CLAIMREVIEW_VERDICT = "CLAIMREVIEW_VERDICT"
    CLAIMREVIEW_SOURCE = "CLAIMREVIEW_SOURCE"
    CLAIMREVIEW_URL = "CLAIMREVIEW_URL"
    CLAIMREVIEW_MATCH_SCORE = "CLAIMREVIEW_MATCH_SCORE"

    # coverage-left|coverage-center|coverage-right
    COVERAGE_ARTICLE_COUNT = "COVERAGE_ARTICLE_COUNT"
    COVERAGE_FRAMING = "COVERAGE_FRAMING"
    COVERAGE_TOP_SOURCE = "COVERAGE_TOP_SOURCE"
    COVERAGE_TOP_SOURCE_URL = "COVERAGE_TOP_SOURCE_URL"

    # blindspot-detector
    BLINDSPOT_SCORE = "BLINDSPOT_SCORE"
    BLINDSPOT_DIRECTION = "BLINDSPOT_DIRECTION"
    CROSS_SPECTRUM_CORROBORATION = "CROSS_SPECTRUM_CORROBORATION"

    # domain-evidence
    DOMAIN_SOURCE_NAME = "DOMAIN_SOURCE_NAME"
    DOMAIN_SOURCE_URL = "DOMAIN_SOURCE_URL"
    DOMAIN_EVIDENCE_ALIGNMENT = "DOMAIN_EVIDENCE_ALIGNMENT"
    DOMAIN_CONFIDENCE = "DOMAIN_CONFIDENCE"

    # synthesizer
    CONFIDENCE_SCORE = "CONFIDENCE_SCORE"
    VERDICT = "VERDICT"
    VERDICT_NARRATIVE = "VERDICT_NARRATIVE"
    SYNTHESIS_SIGNAL_COUNT = "SYNTHESIS_SIGNAL_COUNT"
    SYNTHESIS_OVERRIDE_REASON = "SYNTHESIS_OVERRIDE_REASON"

    # source-validator
    SOURCE_EXTRACTED_URL = "SOURCE_EXTRACTED_URL"
    SOURCE_VALIDATION_STATUS = "SOURCE_VALIDATION_STATUS"
    SOURCE_CONVERGENCE_SCORE = "SOURCE_CONVERGENCE_SCORE"
    CITATION_LIST = "CITATION_LIST"


# Registry metadata keyed by code
_CODE_METADATA: dict[ObservationCode, dict] = {
    ObservationCode.CLAIM_TEXT: {
        "display": "Claim Text",
        "owner_agent": "ingestion-agent",
        "value_type": ValueType.ST,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.CLAIM_SOURCE_URL: {
        "display": "Claim Source URL",
        "owner_agent": "ingestion-agent",
        "value_type": ValueType.ST,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.CLAIM_SOURCE_DATE: {
        "display": "Claim Source Date",
        "owner_agent": "ingestion-agent",
        "value_type": ValueType.ST,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.CLAIM_DOMAIN: {
        "display": "Claim Domain",
        "owner_agent": "ingestion-agent",
        "value_type": ValueType.ST,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.CHECK_WORTHY_SCORE: {
        "display": "Check-Worthy Score",
        "owner_agent": "claim-detector",
        "value_type": ValueType.NM,
        "units": "score",
        "reference_range": "0.0-1.0",
    },
    ObservationCode.CLAIM_NORMALIZED: {
        "display": "Normalized Claim Text",
        "owner_agent": "claim-detector",
        "value_type": ValueType.ST,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.ENTITY_PERSON: {
        "display": "Named Person Entity",
        "owner_agent": "entity-extractor",
        "value_type": ValueType.ST,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.ENTITY_ORG: {
        "display": "Named Organization Entity",
        "owner_agent": "entity-extractor",
        "value_type": ValueType.ST,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.ENTITY_DATE: {
        "display": "Temporal Reference",
        "owner_agent": "entity-extractor",
        "value_type": ValueType.ST,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.ENTITY_LOCATION: {
        "display": "Location Entity",
        "owner_agent": "entity-extractor",
        "value_type": ValueType.ST,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.ENTITY_STATISTIC: {
        "display": "Statistic or Quantity",
        "owner_agent": "entity-extractor",
        "value_type": ValueType.ST,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.CLAIMREVIEW_MATCH: {
        "display": "ClaimReview Match Found",
        "owner_agent": "claimreview-matcher",
        "value_type": ValueType.CWE,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.CLAIMREVIEW_VERDICT: {
        "display": "ClaimReview Verdict",
        "owner_agent": "claimreview-matcher",
        "value_type": ValueType.CWE,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.CLAIMREVIEW_SOURCE: {
        "display": "ClaimReview Source Organization",
        "owner_agent": "claimreview-matcher",
        "value_type": ValueType.ST,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.CLAIMREVIEW_URL: {
        "display": "ClaimReview Source URL",
        "owner_agent": "claimreview-matcher",
        "value_type": ValueType.ST,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.CLAIMREVIEW_MATCH_SCORE: {
        "display": "ClaimReview Semantic Match Score",
        "owner_agent": "claimreview-matcher",
        "value_type": ValueType.NM,
        "units": "score",
        "reference_range": "0.0-1.0",
    },
    ObservationCode.COVERAGE_ARTICLE_COUNT: {
        "display": "Coverage Article Count",
        "owner_agent": "coverage-left|coverage-center|coverage-right",
        "value_type": ValueType.NM,
        "units": "count",
        "reference_range": None,
    },
    ObservationCode.COVERAGE_FRAMING: {
        "display": "Coverage Framing",
        "owner_agent": "coverage-left|coverage-center|coverage-right",
        "value_type": ValueType.CWE,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.COVERAGE_TOP_SOURCE: {
        "display": "Top Coverage Source",
        "owner_agent": "coverage-left|coverage-center|coverage-right",
        "value_type": ValueType.ST,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.COVERAGE_TOP_SOURCE_URL: {
        "display": "Top Coverage Source URL",
        "owner_agent": "coverage-left|coverage-center|coverage-right",
        "value_type": ValueType.ST,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.BLINDSPOT_SCORE: {
        "display": "Coverage Blindspot Score",
        "owner_agent": "blindspot-detector",
        "value_type": ValueType.NM,
        "units": "score",
        "reference_range": "0.0-1.0",
    },
    ObservationCode.BLINDSPOT_DIRECTION: {
        "display": "Blindspot Direction",
        "owner_agent": "blindspot-detector",
        "value_type": ValueType.CWE,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.CROSS_SPECTRUM_CORROBORATION: {
        "display": "Cross-Spectrum Corroboration",
        "owner_agent": "blindspot-detector",
        "value_type": ValueType.CWE,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.DOMAIN_SOURCE_NAME: {
        "display": "Domain Primary Source Name",
        "owner_agent": "domain-evidence",
        "value_type": ValueType.ST,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.DOMAIN_SOURCE_URL: {
        "display": "Domain Primary Source URL",
        "owner_agent": "domain-evidence",
        "value_type": ValueType.ST,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.DOMAIN_EVIDENCE_ALIGNMENT: {
        "display": "Domain Evidence Alignment",
        "owner_agent": "domain-evidence",
        "value_type": ValueType.CWE,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.DOMAIN_CONFIDENCE: {
        "display": "Domain Evidence Confidence",
        "owner_agent": "domain-evidence",
        "value_type": ValueType.NM,
        "units": "score",
        "reference_range": "0.0-1.0",
    },
    ObservationCode.CONFIDENCE_SCORE: {
        "display": "Synthesized Confidence Score",
        "owner_agent": "synthesizer",
        "value_type": ValueType.NM,
        "units": "score",
        "reference_range": "0.0-1.0",
    },
    ObservationCode.VERDICT: {
        "display": "Final Verdict",
        "owner_agent": "synthesizer",
        "value_type": ValueType.CWE,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.VERDICT_NARRATIVE: {
        "display": "Verdict Narrative",
        "owner_agent": "synthesizer",
        "value_type": ValueType.TX,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.SYNTHESIS_SIGNAL_COUNT: {
        "display": "Synthesis Input Signal Count",
        "owner_agent": "synthesizer",
        "value_type": ValueType.NM,
        "units": "count",
        "reference_range": None,
    },
    ObservationCode.SYNTHESIS_OVERRIDE_REASON: {
        "display": "Synthesis Override Reason",
        "owner_agent": "synthesizer",
        "value_type": ValueType.ST,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.SOURCE_EXTRACTED_URL: {
        "display": "Extracted Source URL",
        "owner_agent": "source-validator",
        "value_type": ValueType.ST,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.SOURCE_VALIDATION_STATUS: {
        "display": "Source URL Validation Status",
        "owner_agent": "source-validator",
        "value_type": ValueType.CWE,
        "units": None,
        "reference_range": None,
    },
    ObservationCode.SOURCE_CONVERGENCE_SCORE: {
        "display": "Source Convergence Score",
        "owner_agent": "source-validator",
        "value_type": ValueType.NM,
        "units": "score",
        "reference_range": "0.0-1.0",
    },
    ObservationCode.CITATION_LIST: {
        "display": "Aggregated Citation List",
        "owner_agent": "source-validator",
        "value_type": ValueType.TX,
        "units": None,
        "reference_range": None,
    },
}

# CWE pattern: CODE^Display^CodingSystem
_CWE_PATTERN = re.compile(r"^[A-Z0-9_]+\^.+\^[A-Z0-9_]+$")


def get_code_metadata(code: ObservationCode) -> dict:
    """Return the registry metadata for an observation code."""
    return _CODE_METADATA[code]


class Observation(BaseModel):
    """A single observation published by an agent to a Redis Stream."""

    run_id: str = Field(alias="runId")
    agent: str
    seq: Annotated[int, Field(gt=0)]
    code: ObservationCode
    value: str
    value_type: ValueType = Field(alias="valueType")
    units: str | None = None
    reference_range: str | None = Field(default=None, alias="referenceRange")
    status: str  # EpistemicStatus value (P/F/C/X), validated below
    timestamp: str
    method: str | None = None
    note: Annotated[str | None, Field(default=None, max_length=512)]

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _validate_value_type_matches_code(self) -> "Observation":
        expected = _CODE_METADATA[self.code]["value_type"]
        if self.value_type != expected:
            raise ValueError(
                f"Code {self.code.value} requires valueType {expected.value}, "
                f"got {self.value_type.value}"
            )
        return self

    @model_validator(mode="after")
    def _validate_value_format(self) -> "Observation":
        if self.value_type == ValueType.NM:
            try:
                float(self.value)
            except ValueError:
                raise ValueError(f"NM value must be parseable as float, got: {self.value!r}")
        elif self.value_type == ValueType.CWE:
            if not _CWE_PATTERN.match(self.value):
                raise ValueError(
                    f"CWE value must match CODE^Display^System format, got: {self.value!r}"
                )
        elif self.value_type == ValueType.TX:
            if len(self.value) <= 200:
                raise ValueError(f"TX value must exceed 200 characters, got {len(self.value)}")
        return self

    @model_validator(mode="after")
    def _validate_status(self) -> "Observation":
        from swarm_reasoning.models.status import EpistemicStatus

        try:
            EpistemicStatus(self.status)
        except ValueError:
            raise ValueError(f"Invalid epistemic status: {self.status!r}. Must be P, F, C, or X.")
        return self

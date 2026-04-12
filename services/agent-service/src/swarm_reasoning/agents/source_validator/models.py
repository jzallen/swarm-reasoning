"""Data models for the source-validator agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ValidationStatus(str, Enum):
    """URL validation result status."""

    LIVE = "LIVE"
    DEAD = "DEAD"
    REDIRECT = "REDIRECT"
    SOFT404 = "SOFT404"
    TIMEOUT = "TIMEOUT"

    def to_cwe(self) -> str:
        """Convert to CWE-formatted string (CODE^Display^CodingSystem)."""
        display_map = {
            "LIVE": "Live",
            "DEAD": "Dead",
            "REDIRECT": "Redirect",
            "SOFT404": "Soft 404",
            "TIMEOUT": "Timeout",
        }
        return f"{self.value}^{display_map[self.value]}^FCK"

    def to_citation_status(self) -> str:
        """Convert to lowercase citation status string."""
        status_map = {
            "LIVE": "live",
            "DEAD": "dead",
            "REDIRECT": "redirect",
            "SOFT404": "soft-404",
            "TIMEOUT": "timeout",
        }
        return status_map[self.value]


@dataclass
class UrlAssociation:
    """A single agent/code/name association for an extracted URL."""

    agent: str
    observation_code: str
    source_name: str


@dataclass
class ExtractedUrl:
    """A URL extracted from cross-agent data, with all agent associations."""

    url: str
    associations: list[UrlAssociation] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Result of validating a single URL."""

    url: str
    status: ValidationStatus
    final_url: str | None = None
    error: str | None = None


@dataclass
class Citation:
    """A single citation entry for the CITATION_LIST observation."""

    source_url: str
    source_name: str
    agent: str
    observation_code: str
    validation_status: str
    convergence_count: int

    def to_dict(self) -> dict:
        """Serialize to dict matching the CITATION_LIST JSON schema."""
        return {
            "sourceUrl": self.source_url,
            "sourceName": self.source_name,
            "agent": self.agent,
            "observationCode": self.observation_code,
            "validationStatus": self.validation_status,
            "convergenceCount": self.convergence_count,
        }

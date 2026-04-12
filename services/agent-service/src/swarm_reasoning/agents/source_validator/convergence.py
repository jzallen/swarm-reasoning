"""Source convergence scoring via normalized URL matching."""

from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlparse

from swarm_reasoning.agents.source_validator.models import ExtractedUrl


def normalize_url(url: str) -> str:
    """Normalize a URL for convergence comparison.

    1. Parse with urlparse
    2. Lowercase scheme and netloc
    3. Strip www. prefix from netloc
    4. Remove query params and fragments
    5. Remove trailing slashes from path
    6. Reconstruct as scheme://netloc/path
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.hostname or ""
    netloc = netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # Preserve port if non-standard
    if parsed.port and parsed.port not in (80, 443):
        netloc = f"{netloc}:{parsed.port}"

    path = parsed.path.rstrip("/")
    return f"{scheme}://{netloc}{path}"


def group_by_normalized_url(
    extracted_urls: list[ExtractedUrl],
) -> dict[str, list[ExtractedUrl]]:
    """Group extracted URLs by their normalized form."""
    groups: dict[str, list[ExtractedUrl]] = defaultdict(list)
    for eu in extracted_urls:
        key = normalize_url(eu.url)
        groups[key].append(eu)
    return dict(groups)


class ConvergenceAnalyzer:
    """Computes source convergence metrics across agents."""

    def compute_convergence_score(self, extracted_urls: list[ExtractedUrl]) -> float:
        """Compute convergence score: (URLs cited by 2+ agents) / total unique URLs.

        Returns 0.0 if no URLs, rounded to 4 decimal places.
        """
        groups = group_by_normalized_url(extracted_urls)
        if not groups:
            return 0.0

        converging = 0
        for _norm_url, url_list in groups.items():
            agents = set()
            for eu in url_list:
                for assoc in eu.associations:
                    agents.add(assoc.agent)
            if len(agents) >= 2:
                converging += 1

        return round(converging / len(groups), 4)

    def get_convergence_groups(self, extracted_urls: list[ExtractedUrl]) -> dict[str, int]:
        """Get convergence count (distinct agents) per normalized URL.

        Returns dict mapping normalized URL -> agent count.
        """
        groups = group_by_normalized_url(extracted_urls)
        counts: dict[str, int] = {}
        for norm_url, url_list in groups.items():
            agents = set()
            for eu in url_list:
                for assoc in eu.associations:
                    agents.add(assoc.agent)
            counts[norm_url] = len(agents)
        return counts

    def get_convergence_count(self, url: str, convergence_groups: dict[str, int]) -> int:
        """Get the convergence count for a specific URL."""
        norm = normalize_url(url)
        return convergence_groups.get(norm, 1)

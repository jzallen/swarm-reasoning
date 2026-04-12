"""Link extraction from cross-agent observation data."""

from __future__ import annotations

import ipaddress
import logging
from urllib.parse import urlparse

from swarm_reasoning.agents.source_validator.models import ExtractedUrl, UrlAssociation

logger = logging.getLogger(__name__)

# Private IP ranges to reject
_PRIVATE_NETLOCS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})


def _is_private_ip(host: str) -> bool:
    """Check if a hostname is a private/reserved IP address."""
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback or addr.is_reserved
    except ValueError:
        return False


def _is_valid_url(url: str) -> bool:
    """Check if a URL is valid for extraction (HTTP/HTTPS, not private)."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    netloc = parsed.hostname or ""
    if not netloc:
        return False

    if netloc in _PRIVATE_NETLOCS:
        return False

    if _is_private_ip(netloc):
        return False

    return True


class LinkExtractor:
    """Extracts and deduplicates URLs from cross-agent observation data."""

    def extract_urls(self, cross_agent_data: dict) -> list[ExtractedUrl]:
        """Parse URLs from Temporal activity input, deduplicate by exact URL.

        Input format: cross_agent_data["urls"] = [
            {"url": "...", "agent": "...", "code": "...", "source_name": "..."},
            ...
        ]
        """
        url_entries = cross_agent_data.get("urls", [])
        if not url_entries:
            return []

        # Group by exact URL, preserving all associations
        url_map: dict[str, ExtractedUrl] = {}

        for entry in url_entries:
            url = entry.get("url", "")
            agent = entry.get("agent", "")
            code = entry.get("code", "")
            source_name = entry.get("source_name", "")

            if not url or not agent:
                continue

            if not _is_valid_url(url):
                logger.warning("Skipping invalid URL: %s (agent=%s)", url, agent)
                continue

            assoc = UrlAssociation(
                agent=agent,
                observation_code=code,
                source_name=source_name,
            )

            if url in url_map:
                url_map[url].associations.append(assoc)
            else:
                url_map[url] = ExtractedUrl(url=url, associations=[assoc])

        return list(url_map.values())

"""Validation report generator: JSON and human-readable output."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from tests.validation.comparison import NfrAssessment
from tests.validation.scorer import ClaimResult, compute_alignment_rate


@dataclass
class CategorySummary:
    """Per-category accuracy summary."""

    category: str
    total_claims: int
    aligned_claims: int
    alignment_rate: float
    mean_confidence: float
    mean_signal_count: float


@dataclass
class ValidationReport:
    """Complete validation report."""

    run_timestamp: str
    corpus_version: str
    total_claims: int
    overall_alignment_rate: float
    per_category: list[CategorySummary]
    per_claim: list[dict]
    nfr_assessment: dict
    baseline_comparison: dict | None


def build_category_summary(
    category: str,
    results: list[ClaimResult],
) -> CategorySummary:
    """Build summary for a single corpus category."""
    if not results:
        return CategorySummary(
            category=category,
            total_claims=0,
            aligned_claims=0,
            alignment_rate=0.0,
            mean_confidence=0.0,
            mean_signal_count=0.0,
        )

    aligned = sum(1 for r in results if r.aligned)
    return CategorySummary(
        category=category,
        total_claims=len(results),
        aligned_claims=aligned,
        alignment_rate=aligned / len(results),
        mean_confidence=sum(r.confidence_score for r in results) / len(results),
        mean_signal_count=sum(r.signal_count for r in results) / len(results),
    )


def build_report(
    corpus_version: str,
    all_results: list[ClaimResult],
    category_map: dict[str, list[str]],
    nfr: NfrAssessment,
    baseline_comparison: dict | None = None,
) -> ValidationReport:
    """Build a complete validation report."""
    # Group results by category
    category_summaries = []
    for cat_name, claim_ids in category_map.items():
        cat_results = [r for r in all_results if r.claim_id in claim_ids]
        category_summaries.append(build_category_summary(cat_name, cat_results))

    return ValidationReport(
        run_timestamp=datetime.now(timezone.utc).isoformat(),
        corpus_version=corpus_version,
        total_claims=len(all_results),
        overall_alignment_rate=compute_alignment_rate(all_results),
        per_category=category_summaries,
        per_claim=[asdict(r) for r in all_results],
        nfr_assessment=asdict(nfr),
        baseline_comparison=baseline_comparison,
    )


def write_report(report: ValidationReport, output_dir: str | Path) -> Path:
    """Write report to a timestamped JSON file. Returns the file path."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = output_dir / f"report-{timestamp}.json"

    data = asdict(report)
    path.write_text(json.dumps(data, indent=2, default=str))
    return path


def format_table(report: ValidationReport) -> str:
    """Format a human-readable summary table."""
    lines = [
        "=" * 72,
        f"  Validation Report — {report.run_timestamp}",
        f"  Corpus v{report.corpus_version} | {report.total_claims} claims",
        "=" * 72,
        "",
        f"  Overall Alignment: {report.overall_alignment_rate:.1%}",
        "",
        "  Category Breakdown:",
        f"  {'Category':<28} {'Aligned':>8} {'Rate':>8} {'Conf':>8} {'Signals':>8}",
        "  " + "-" * 60,
    ]

    for cat in report.per_category:
        lines.append(
            f"  {cat.category:<28} "
            f"{cat.aligned_claims:>3}/{cat.total_claims:<3}  "
            f"{cat.alignment_rate:>7.1%} "
            f"{cat.mean_confidence:>7.2f} "
            f"{cat.mean_signal_count:>7.1f}"
        )

    lines.extend([
        "",
        "  NFR Assessment:",
        f"    NFR-019 (accuracy):  {report.nfr_assessment['nfr_019_rate']:.1%}"
        f"  MUST({'PASS' if report.nfr_assessment['nfr_019_must'] else 'FAIL'})"
        f"  PLAN({'PASS' if report.nfr_assessment['nfr_019_plan'] else 'FAIL'})"
        f"  WISH({'PASS' if report.nfr_assessment['nfr_019_wish'] else 'FAIL'})",
    ])

    if report.baseline_comparison:
        gap = report.nfr_assessment.get("nfr_020_gap_pp", 0)
        lines.append(
            f"    NFR-020 (advantage): {gap:+.1f}pp"
            f"  MUST({'PASS' if report.nfr_assessment['nfr_020_must'] else 'FAIL'})"
            f"  PLAN({'PASS' if report.nfr_assessment['nfr_020_plan'] else 'FAIL'})"
            f"  WISH({'PASS' if report.nfr_assessment['nfr_020_wish'] else 'FAIL'})"
        )

    lines.extend(["", "=" * 72])
    return "\n".join(lines)

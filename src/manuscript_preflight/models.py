"""Core data structures and mandatory provenance/non-defamation notices."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Severity = Literal["FAIL", "WARN", "PASS"]
CheckCategory = Literal[
    "citation_notice",
    "citation_resolution",
    "citation_metadata_mismatch",
    "grim_granularity",
    "statcheck_pvalue",
    "cohort_sample_drift",
    "tier_limit",
]

SCOPE_AND_PROVENANCE_NOTICE = (
    "Scope & Provenance Notice: Manuscript Preflight CI performs mechanical bibliographic "
    "metadata lookups (via Crossref, Retraction Watch, OpenAlex CC0, and NCBI PubMed E-utilities) "
    "and arithmetic consistency checks for author verification only. Zero manuscript prose or "
    "publisher abstracts are stored or redistributed. Flags reflect upstream registry statuses "
    "(e.g., ErratumIn vs. RetractionIn) or rounding ambiguities and do not constitute "
    "academic-integrity findings, peer review, or legal determinations."
)

PILOT_RESERVATION_URL = (
    "https://cjprybol.github.io/app-portfolio-landing-pages/manuscript-preflight-ci/"
)
FREE_LOCAL_BIB_LIMIT = 25


@dataclass(frozen=True)
class BibEntry:
    """Normalized bibliography entry from .bib or inline manuscript references."""

    key: str
    entry_type: str = "article"
    title: str = ""
    year: str = ""
    doi: str | None = None
    pmid: str | None = None
    raw_source: str = ""


@dataclass(frozen=True)
class TableCohort:
    """Extracted table arm sample sizes for reconciliation against prose totals."""

    label: str
    arm_counts: tuple[int, ...]
    stated_total: int | None = None
    line_number: int = 0

    @property
    def arm_sum(self) -> int:
        return sum(self.arm_counts)


@dataclass(frozen=True)
class PreflightFinding:
    """Single deterministic preflight diagnostic."""

    severity: Severity
    category: CheckCategory
    code: str
    subject: str
    message: str
    location: str = ""
    evidence_url: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PreflightReport:
    """Complete preflight run output."""

    manuscript_path: str
    bib_path: str | None
    tier_mode: str
    references_total: int
    references_checked: int
    references_clean: int
    findings: tuple[PreflightFinding, ...] = field(default_factory=tuple)
    scope_notice: str = SCOPE_AND_PROVENANCE_NOTICE

    @property
    def fail_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "FAIL")

    @property
    def warn_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "WARN")

    def to_dict(self) -> dict[str, object]:
        return {
            "manuscript_path": self.manuscript_path,
            "bib_path": self.bib_path,
            "tier_mode": self.tier_mode,
            "references_total": self.references_total,
            "references_checked": self.references_checked,
            "references_clean": self.references_clean,
            "fail_count": self.fail_count,
            "warn_count": self.warn_count,
            "findings": [f.to_dict() for f in self.findings],
            "scope_notice": self.scope_notice,
        }

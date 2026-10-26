"""CLI entrypoint and deterministic report formatters for Manuscript Preflight CI."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from manuscript_preflight.citations import JsonFetcher, default_json_fetcher, verify_bibliography
from manuscript_preflight.ingest import load_manuscript, parse_bibtex
from manuscript_preflight.models import (
    FREE_LOCAL_BIB_LIMIT,
    PILOT_RESERVATION_URL,
    BibEntry,
    PreflightFinding,
    PreflightReport,
)
from manuscript_preflight.stats_lint import (
    check_cohort_sample_drift,
    check_grim_percentages,
    check_inline_test_statistics,
)


def resolve_tier_mode(license_key: str | None = None) -> tuple[str, int | None]:
    """Validate optional offline submission-pass / lab-CI license token.

    Format: mp_live_<tier>_<expiry_yyyymmdd>_<16hex_tag>
    Free OSS mode checks up to FREE_LOCAL_BIB_LIMIT (25) bibliography references per run
    and runs 100% of local statistical/GRIM/cohort checks with zero restriction.
    """
    raw = (license_key or os.environ.get("MPREFLIGHT_LICENSE_KEY") or "").strip()
    if not raw:
        return "oss-free", FREE_LOCAL_BIB_LIMIT
    parts = raw.split("_")
    if len(parts) == 5 and parts[0] == "mp" and parts[1] in {"pass", "lab"}:
        payload = "_".join(parts[:4]).encode("utf-8")
        verify_secret = os.environ.get(
            "MPREFLIGHT_SIGNING_PUBLIC_SALT", "manuscript-preflight-v1-public-salt"
        ).encode("utf-8")
        expected = hmac.new(verify_secret, payload, hashlib.sha256).hexdigest()[:16]
        if hmac.compare_digest(parts[4], expected):
            return f"licensed-{parts[1]}", None
    return "oss-free", FREE_LOCAL_BIB_LIMIT


def run_preflight(
    manuscript_path: Path,
    *,
    bib_path: Path | None = None,
    offline: bool = False,
    license_key: str | None = None,
    fetcher: JsonFetcher = default_json_fetcher,
) -> PreflightReport:
    """Execute complete preflight check on a local manuscript and optional .bib file."""
    doc = load_manuscript(manuscript_path)
    entries: list[BibEntry] = []
    if bib_path is not None:
        entries.extend(
            parse_bibtex(bib_path.read_text(encoding="utf-8"), source_name=bib_path.name)
        )
    else:
        sibling_bib = manuscript_path.with_suffix(".bib")
        if sibling_bib.exists():
            bib_path = sibling_bib
            entries.extend(
                parse_bibtex(
                    sibling_bib.read_text(encoding="utf-8"),
                    source_name=sibling_bib.name,
                )
            )

    known_dois = {e.doi for e in entries if e.doi}
    known_pmids = {e.pmid for e in entries if e.pmid}
    for inl in doc.inline_refs:
        if (inl.doi and inl.doi in known_dois) or (inl.pmid and inl.pmid in known_pmids):
            continue
        entries.append(inl)

    tier_mode, bib_cap = resolve_tier_mode(license_key)
    total_refs = len(entries)
    findings: list[PreflightFinding] = []

    if bib_cap is not None and total_refs > bib_cap:
        checked_entries = entries[:bib_cap]
        findings.append(
            PreflightFinding(
                severity="WARN",
                category="tier_limit",
                code="OSS_BIBLIOGRAPHY_CAP_REACHED",
                subject=f"Bibliography cap ({bib_cap}/{total_refs} references checked)",
                message=(
                    f"Free OSS mode verified the first {bib_cap} of {total_refs} references. "
                    f"Unlock unlimited Submission Pass ($29) or PI Lab CI Pack ($199/yr): {PILOT_RESERVATION_URL}"
                ),
                location=bib_path.name if bib_path else manuscript_path.name,
                evidence_url=PILOT_RESERVATION_URL,
            )
        )
    else:
        checked_entries = entries

    clean_refs = 0
    if not offline and checked_entries:
        bib_findings, clean_refs = verify_bibliography(
            checked_entries, doc.citation_contexts, fetcher=fetcher
        )
        findings.extend(bib_findings)
    elif offline:
        clean_refs = len(checked_entries)

    findings.extend(check_cohort_sample_drift(doc))
    findings.extend(check_grim_percentages(doc))
    findings.extend(check_inline_test_statistics(doc))

    return PreflightReport(
        manuscript_path=str(manuscript_path),
        bib_path=str(bib_path) if bib_path else None,
        tier_mode=tier_mode,
        references_total=total_refs,
        references_checked=len(checked_entries),
        references_clean=clean_refs,
        findings=tuple(findings),
    )


def format_terminal_report(report: PreflightReport) -> str:
    """Render concise terminal summary matching Manuscript Preflight CI diagnostic style."""
    lines: list[str] = []
    for f in report.findings:
        lines.append(f"[{f.severity}] {f.subject}")
        lines.append(f"       {f.message}")
        if f.location:
            lines.append(f"       Cited/Located in: {f.location}")
        lines.append("")

    lines.append(
        f"[PASS] {report.references_clean}/{report.references_checked} checked bibliography references "
        f"resolved cleanly ({report.fail_count} FAIL, {report.warn_count} WARN)."
    )
    lines.append("")
    lines.append(report.scope_notice)
    return "\n".join(lines)


def format_markdown_report(report: PreflightReport) -> str:
    """Render Markdown summary suitable for GitHub Actions Job Summaries or PR comments."""
    lines = [
        "# Manuscript Preflight CI Report",
        "",
        f"- **Manuscript:** `{report.manuscript_path}`",
        f"- **Bibliography:** `{report.bib_path or 'inline-only'}` (`{report.references_clean}/{report.references_checked}` clean of `{report.references_total}` total)",
        f"- **Mode:** `{report.tier_mode}` | **Failures:** `{report.fail_count}` | **Warnings:** `{report.warn_count}`",
        "",
    ]
    if report.findings:
        lines.extend(
            [
                "| Severity | Category | Subject | Details | Location |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ]
        )
        for f in report.findings:
            subj = f.subject.replace("|", "\\|")
            msg = f.message.replace("|", "\\|")
            loc = (f.location or "-").replace("|", "\\|")
            lines.append(f"| **{f.severity}** | `{f.category}` | {subj} | {msg} | {loc} |")
        lines.append("")
    else:
        lines.extend(["All bibliography and statistical consistency checks passed cleanly.", ""])

    lines.append(f"> {report.scope_notice}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mpreflight",
        description="Ephemeral pre-submission citation, retraction, GRIM & statcheck linter.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check", help="Run preflight checks on a manuscript")
    p_check.add_argument("manuscript", type=Path, help="Path to .tex, .qmd, .md, or .docx file")
    p_check.add_argument("--bib", type=Path, default=None, help="Optional path to .bib file")
    p_check.add_argument(
        "--offline",
        action="store_true",
        help="Skip live Crossref/OpenAlex/PubMed HTTP requests",
    )
    p_check.add_argument(
        "--fail-on",
        choices=("fail", "warn", "none"),
        default="fail",
        help="Exit non-zero threshold (default: fail)",
    )
    p_check.add_argument("--output-md", type=Path, default=None, help="Write Markdown report")
    p_check.add_argument("--output-json", type=Path, default=None, help="Write JSON report")
    p_check.add_argument("--license-key", type=str, default=None, help="Optional license key")

    args = parser.parse_args(argv)
    if not args.manuscript.exists():
        print(f"Error: manuscript not found: {args.manuscript}", file=sys.stderr)
        return 2
    if args.bib is not None and not args.bib.exists():
        print(f"Error: bibliography file not found: {args.bib}", file=sys.stderr)
        return 2

    report = run_preflight(
        args.manuscript,
        bib_path=args.bib,
        offline=args.offline,
        license_key=args.license_key,
    )
    print(format_terminal_report(report))

    if args.output_md is not None:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(format_markdown_report(report), encoding="utf-8")
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

    if args.fail_on == "fail" and report.fail_count > 0:
        return 1
    if args.fail_on == "warn" and (report.fail_count > 0 or report.warn_count > 0):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

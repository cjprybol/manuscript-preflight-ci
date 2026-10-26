"""Live bibliographic & post-publication notice verification (Crossref, OpenAlex CC0, PubMed)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from manuscript_preflight.models import BibEntry, PreflightFinding

JsonFetcher = Callable[[str], tuple[int, dict[str, Any] | None]]

USER_AGENT = (
    "manuscript-preflight-ci/0.1.0 "
    "(+https://cjprybol.github.io/app-portfolio-landing-pages/manuscript-preflight-ci/)"
)

_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "into",
        "using",
        "study",
        "analysis",
        "between",
        "among",
        "after",
        "during",
    }
)


def default_json_fetcher(url: str, timeout: float = 8.0) -> tuple[int, dict[str, Any] | None]:
    """Perform a polite GET request returning (http_status, parsed_json_or_none)."""
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200))
            payload = json.loads(resp.read().decode("utf-8"))
            return status, payload if isinstance(payload, dict) else None
    except urllib.error.HTTPError as exc:
        return int(exc.code), None
    except Exception:
        return 0, None


def _title_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]{3,}", title.lower())
    return {w for w in words if w not in _STOPWORDS}


def title_jaccard_similarity(a: str, b: str) -> float:
    """Compute token Jaccard overlap to catch LLM-hallucinated DOI/title swaps."""
    ta = _title_tokens(a)
    tb = _title_tokens(b)
    if not ta or not tb:
        return 1.0
    return len(ta & tb) / len(ta | tb)


def _normalize_notice_label(raw_type: str) -> tuple[str, str]:
    """Map Crossref / Retraction Watch / PubMed update types to (canonical_label, severity)."""
    low = raw_type.lower().strip()
    if "retract" in low or "withdrawal" in low:
        return "RetractionIn", "FAIL"
    if "concern" in low:
        return "ExpressionOfConcernIn", "FAIL"
    if "errat" in low or "corrigend" in low or "correction" in low:
        return "ErratumIn", "WARN"
    return raw_type, "WARN"


def verify_bibliography(
    entries: list[BibEntry],
    citation_contexts: dict[str, tuple[str, ...]],
    *,
    fetcher: JsonFetcher = default_json_fetcher,
) -> tuple[list[PreflightFinding], int]:
    """Verify bibliography entries against Crossref, OpenAlex CC0, and NCBI PubMed metadata.

    Returns (findings, clean_resolved_count). Never stores or redistributes abstracts.
    """
    findings: list[PreflightFinding] = []
    clean_count = 0

    for entry in entries:
        locs = (
            citation_contexts.get(entry.key)
            or (citation_contexts.get(entry.doi or "") if entry.doi else None)
            or (citation_contexts.get(f"PMID:{entry.pmid}") if entry.pmid else None)
            or ()
        )
        loc_str = ", ".join(locs[:3]) if locs else entry.raw_source

        if not entry.doi and not entry.pmid:
            findings.append(
                PreflightFinding(
                    severity="WARN",
                    category="citation_resolution",
                    code="MISSING_PERSISTENT_ID",
                    subject=f"ref:{entry.key}",
                    message=f"Reference '{entry.key}' has neither a DOI nor a PMID for upstream verification.",
                    location=loc_str,
                )
            )
            continue

        entry_failed_or_warned = False

        if entry.doi:
            enc_doi = urllib.parse.quote(entry.doi, safe="")
            cr_url = f"https://api.crossref.org/works/{enc_doi}"
            status, cr_json = fetcher(cr_url)

            if status == 404:
                findings.append(
                    PreflightFinding(
                        severity="FAIL",
                        category="citation_resolution",
                        code="UNRESOLVED_DOI_404",
                        subject=f"ref:{entry.key} (DOI {entry.doi})",
                        message=(
                            f"DOI {entry.doi} returned HTTP 404 on Crossref "
                            "(possible typo or hallucinated citation)."
                        ),
                        location=loc_str,
                        evidence_url=f"https://doi.org/{entry.doi}",
                    )
                )
                continue

            if status == 200 and cr_json and isinstance(cr_json.get("message"), dict):
                msg = cr_json["message"]
                cr_titles = msg.get("title") or []
                upstream_title = cr_titles[0] if isinstance(cr_titles, list) and cr_titles else ""
                if entry.title and upstream_title:
                    sim = title_jaccard_similarity(entry.title, str(upstream_title))
                    if sim < 0.22:
                        entry_failed_or_warned = True
                        findings.append(
                            PreflightFinding(
                                severity="FAIL",
                                category="citation_metadata_mismatch",
                                code="DOI_TITLE_MISMATCH",
                                subject=f"ref:{entry.key} (DOI {entry.doi})",
                                message=(
                                    f"Bibliography title ('{entry.title[:70]}') does not match "
                                    f"Crossref metadata ('{str(upstream_title)[:70]}'; token overlap={sim:.0%})."
                                ),
                                location=loc_str,
                                evidence_url=f"https://doi.org/{entry.doi}",
                            )
                        )

                updates = list(msg.get("update-to") or []) + list(msg.get("updated-by") or [])
                for upd in updates:
                    if not isinstance(upd, dict):
                        continue
                    raw_type = str(upd.get("type") or upd.get("label") or "Update")
                    notice_label, sev = _normalize_notice_label(raw_type)
                    upd_doi = str(upd.get("DOI") or entry.doi)
                    upd_source = str(upd.get("source") or "Crossref")
                    entry_failed_or_warned = True
                    findings.append(
                        PreflightFinding(
                            severity=sev,  # type: ignore[arg-type]
                            category="citation_notice",
                            code=f"UPSTREAM_{notice_label.upper()}",
                            subject=f"ref:{entry.key} (DOI {entry.doi})",
                            message=(
                                f"Notice: {notice_label} recorded via {upd_source} "
                                f"(notice DOI: {upd_doi}). Verify before submission."
                            ),
                            location=loc_str,
                            evidence_url=f"https://doi.org/{upd_doi}",
                        )
                    )

            # Secondary CC0 verification via OpenAlex
            oa_url = f"https://api.openalex.org/works/https://doi.org/{enc_doi}"
            oa_status, oa_json = fetcher(oa_url)
            if oa_status == 200 and oa_json and bool(oa_json.get("is_retracted")):
                already_flagged_retraction = any(
                    f.subject == f"ref:{entry.key} (DOI {entry.doi})"
                    and f.code == "UPSTREAM_RETRACTIONIN"
                    for f in findings
                )
                if not already_flagged_retraction:
                    entry_failed_or_warned = True
                    findings.append(
                        PreflightFinding(
                            severity="FAIL",
                            category="citation_notice",
                            code="UPSTREAM_RETRACTIONIN",
                            subject=f"ref:{entry.key} (DOI {entry.doi})",
                            message=(
                                "Notice: RetractionIn flagged in OpenAlex (CC0) work record "
                                f"for DOI {entry.doi}. Verify before submission."
                            ),
                            location=loc_str,
                            evidence_url=f"https://doi.org/{entry.doi}",
                        )
                    )

        if entry.pmid:
            pm_url = (
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
                f"?db=pubmed&id={urllib.parse.quote(entry.pmid)}&retmode=json"
            )
            pm_status, pm_json = fetcher(pm_url)
            if pm_status == 200 and pm_json and isinstance(pm_json.get("result"), dict):
                rec = pm_json["result"].get(entry.pmid)
                if not isinstance(rec, dict) or "error" in rec:
                    entry_failed_or_warned = True
                    findings.append(
                        PreflightFinding(
                            severity="FAIL",
                            category="citation_resolution",
                            code="UNRESOLVED_PMID",
                            subject=f"ref:{entry.key} (PMID:{entry.pmid})",
                            message=f"PMID:{entry.pmid} could not be resolved in NCBI PubMed.",
                            location=loc_str,
                            evidence_url=f"https://pubmed.ncbi.nlm.nih.gov/{entry.pmid}/",
                        )
                    )
                else:
                    pubtypes = [str(p) for p in (rec.get("pubtype") or [])]
                    for pt in pubtypes:
                        low_pt = pt.lower()
                        if "retracted publication" in low_pt or "retraction of publication" in low_pt:
                            entry_failed_or_warned = True
                            findings.append(
                                PreflightFinding(
                                    severity="FAIL",
                                    category="citation_notice",
                                    code="PUBMED_RETRACTIONIN",
                                    subject=f"ref:{entry.key} (PMID:{entry.pmid})",
                                    message=(
                                        f"Notice: PubMed pubtype '{pt}' recorded on PMID:{entry.pmid}."
                                    ),
                                    location=loc_str,
                                    evidence_url=f"https://pubmed.ncbi.nlm.nih.gov/{entry.pmid}/",
                                )
                            )
                        elif "expression of concern" in low_pt or "published erratum" in low_pt:
                            sev = "FAIL" if "concern" in low_pt else "WARN"
                            lbl = "ExpressionOfConcernIn" if "concern" in low_pt else "ErratumIn"
                            entry_failed_or_warned = True
                            findings.append(
                                PreflightFinding(
                                    severity=sev,  # type: ignore[arg-type]
                                    category="citation_notice",
                                    code=f"PUBMED_{lbl.upper()}",
                                    subject=f"ref:{entry.key} (PMID:{entry.pmid})",
                                    message=(
                                        f"Notice: {lbl} ('{pt}') recorded on PMID:{entry.pmid}."
                                    ),
                                    location=loc_str,
                                    evidence_url=f"https://pubmed.ncbi.nlm.nih.gov/{entry.pmid}/",
                                )
                            )

        if not entry_failed_or_warned:
            clean_count += 1

    return findings, clean_count

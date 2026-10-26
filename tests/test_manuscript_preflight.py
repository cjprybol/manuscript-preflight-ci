"""Unit and integration tests for Manuscript Preflight CI."""

from __future__ import annotations

import hmac
import hashlib
import zipfile
from pathlib import Path
from typing import Any

import pytest

from manuscript_preflight.cli import main, resolve_tier_mode, run_preflight
from manuscript_preflight.stats_lint import (
    chi2_pvalue,
    f_pvalue,
    two_tailed_r_pvalue,
    two_tailed_t_pvalue,
    two_tailed_z_pvalue,
)


def test_exact_statistical_distributions_match_reference_critical_values() -> None:
    # Student t: t(18) = 2.100922 -> two-tailed p = 0.05
    assert two_tailed_t_pvalue(2.100922, 18) == pytest.approx(0.05, abs=1e-5)
    # Fisher F: F(1, 20) = 4.351244 -> upper-tail p = 0.05
    assert f_pvalue(4.351244, 1, 20) == pytest.approx(0.05, abs=1e-5)
    # Chi-square: chi2(1) = 3.841459 -> upper-tail p = 0.05
    assert chi2_pvalue(3.841459, 1) == pytest.approx(0.05, abs=1e-5)
    # Standard normal z: z = 1.959964 -> two-tailed p = 0.05
    assert two_tailed_z_pvalue(1.959964) == pytest.approx(0.05, abs=1e-5)
    # Pearson r: r(28) = 0.361007 -> t = 2.0484 -> p = 0.05
    assert two_tailed_r_pvalue(0.361007, 28) == pytest.approx(0.05, abs=1e-4)


def test_end_to_end_retraction_hallucinated_bib_grim_statcheck_and_cohort_drift(
    tmp_path: Path,
) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(
        """
@article{Lesne2006,
  title = {A specific amyloid-beta protein assembly in the brain impairs memory},
  author = {Lesne, Sylvain and others},
  year = {2006},
  doi = {10.1038/nature04533}
}
@article{Hallucinated2024,
  title = {Quantum transformer neural scaling in single-cell transcriptomics},
  author = {Doe, Jane},
  year = {2024},
  doi = {10.1093/bioinformatics/btab001}
}
@article{BrokenDoi2025,
  title = {Nonexistent fabricated citation},
  year = {2025},
  doi = {10.9999/nonexistent.2025.001}
}
@article{CleanPaper2023,
  title = {Reproducible statistical workflows in computational biology},
  year = {2023},
  doi = {10.1371/journal.pcbi.1009999}
}
""",
        encoding="utf-8",
    )

    tex = tmp_path / "manuscript.md"
    tex.write_text(
        """# Results

As established in the oligomer literature @Lesne2006 and recent benchmarks @CleanPaper2023,
we also compared @Hallucinated2024 and @BrokenDoi2025.

In total, n = 142 evaluable patients completed baseline imaging.
Table 2 summarizes baseline characteristics:

| Characteristic | Arm A (n = 71) | Arm B (n = 68) |
| :--- | :--- | :--- |
| Prior therapy | 34.8% (n = 19) | 50.0% (n = 20) |

Primary endpoint differed significantly, t(20) = 1.50, p = 0.012, whereas secondary
biomarker correlation was consistent, r(28) = 0.361, p = 0.050.
""",
        encoding="utf-8",
    )

    def mock_fetcher(url: str) -> tuple[int, dict[str, Any] | None]:
        if "10.1038%2Fnature04533" in url and "crossref" in url:
            return 200, {
                "message": {
                    "title": ["A specific amyloid-beta protein assembly in the brain impairs memory"],
                    "update-to": [
                        {
                            "type": "retraction",
                            "DOI": "10.1038/s41586-024-07691-8",
                            "source": "retraction-watch",
                        }
                    ],
                }
            }
        if "10.1093%2Fbioinformatics%2Fbtab001" in url and "crossref" in url:
            return 200, {
                "message": {
                    "title": ["Fast alignment of metagenomic reads on CPU clusters"],
                }
            }
        if "10.9999%2Fnonexistent" in url and "crossref" in url:
            return 404, None
        if "10.1371%2Fjournal.pcbi.1009999" in url and "crossref" in url:
            return 200, {
                "message": {
                    "title": ["Reproducible statistical workflows in computational biology"],
                }
            }
        if "openalex.org" in url:
            return 200, {"is_retracted": "nature04533" in url}
        return 200, {}

    report = run_preflight(tex, bib_path=bib, fetcher=mock_fetcher)
    codes = {f.code for f in report.findings}
    assert "UPSTREAM_RETRACTIONIN" in codes
    assert "DOI_TITLE_MISMATCH" in codes
    assert "UNRESOLVED_DOI_404" in codes
    assert "PROSE_VS_TABLE_N_DRIFT" in codes
    assert "GRIM_PERCENTAGE_INCONSISTENT" in codes
    assert "DECISION_PVALUE_FLIP" in codes
    assert report.references_clean == 1
    assert report.fail_count >= 4


def test_docx_extraction_and_cli_exit_codes(tmp_path: Path) -> None:
    docx_path = tmp_path / "draft.docx"
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>Cohort included n = 100 patients in primary analysis.</w:t></w:r></w:p>
        <w:tbl>
          <w:tr>
            <w:tc><w:p><w:r><w:t>Metric</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>Control (n = 48)</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>Treated (n = 49)</w:t></w:r></w:p></w:tc>
          </w:tr>
        </w:tbl>
        <w:p><w:r><w:t>Comparison showed z = 0.80, p = 0.010.</w:t></w:r></w:p>
      </w:body>
    </w:document>"""
    with zipfile.ZipFile(docx_path, "w") as zf:
        zf.writestr("word/document.xml", document_xml)

    md_out = tmp_path / "out.md"
    json_out = tmp_path / "out.json"
    rc = main(
        [
            "check",
            str(docx_path),
            "--offline",
            "--output-md",
            str(md_out),
            "--output-json",
            str(json_out),
        ]
    )
    assert rc == 1
    assert md_out.exists()
    assert json_out.exists()
    md_text = md_out.read_text(encoding="utf-8")
    assert "PROSE_VS_TABLE_N_DRIFT" in json_out.read_text(encoding="utf-8")
    assert "DECISION_PVALUE_FLIP" in json_out.read_text(encoding="utf-8")
    assert "Scope & Provenance Notice" in md_text


def test_license_key_unlocks_unlimited_bibliography_cap(tmp_path: Path) -> None:
    payload = b"mp_lab_20271026_inst01"
    sig = hmac.new(
        b"manuscript-preflight-v1-public-salt", payload, hashlib.sha256
    ).hexdigest()[:16]
    valid_key = f"{payload.decode()}_{sig}"
    mode, cap = resolve_tier_mode(valid_key)
    assert mode == "licensed-lab"
    assert cap is None

    free_mode, free_cap = resolve_tier_mode("invalid_key")
    assert free_mode == "oss-free"
    assert free_cap == 25


def test_pubmed_notices_latex_tables_grim_valid_ratios_and_oss_cap(
    tmp_path: Path,
) -> None:
    # Build 27 BibTeX entries to exercise the 25-ref OSS cap + PubMed notice parsing
    bib_lines = [
        """@article{RetractedPmid,
  title = {Retracted clinical biomarker report},
  year = {2021},
  pmid = {33399911}
}""",
        """@article{ErratumPmid,
  title = {Corrected dosing table report},
  year = {2022},
  pmid = {33399922}
}""",
    ]
    for idx in range(25):
        bib_lines.append(
            f"""@article{{Ref{idx:02d},
  title = {{Clean study {idx}}},
  year = {{2024}},
  doi = {{10.1000/clean.{idx:02d}}}
}}"""
        )
    bib = tmp_path / "large.bib"
    bib.write_text("\n".join(bib_lines), encoding="utf-8")

    tex = tmp_path / "paper.tex"
    tex.write_text(
        r"""\section{Results}
Prior cohorts \citep{RetractedPmid,ErratumPmid} enrolled N = 120 participants.
\begin{table}
\caption{Table 1: Baseline arms}
\begin{tabular}{lcc}
Arm & Placebo (n = 60) & Active (n = 60) \\
Response & 31.6\% (n = 19) & 36.8\% (n = 19) \\
\end{tabular}
\end{table}
ANOVA showed F(1, 20) = 4.35, p < 0.001 and \chi^2(1) = 3.84, p = 0.050.
""",
        encoding="utf-8",
    )

    def mock_fetcher(url: str) -> tuple[int, dict[str, Any] | None]:
        if "33399911" in url:
            return 200, {
                "result": {
                    "33399911": {"pubtype": ["Journal Article", "Retracted Publication"]}
                }
            }
        if "33399922" in url:
            return 200, {
                "result": {
                    "33399922": {"pubtype": ["Journal Article", "Published Erratum"]}
                }
            }
        return 200, {"message": {"title": ["Clean study"]}}

    report = run_preflight(tex, bib_path=bib, fetcher=mock_fetcher)
    codes = [f.code for f in report.findings]
    assert report.references_total == 27
    assert report.references_checked == 25
    assert "OSS_BIBLIOGRAPHY_CAP_REACHED" in codes
    assert "PUBMED_RETRACTIONIN" in codes
    assert "PUBMED_ERRATUMIN" in codes
    # 6/19 = 31.6% and 7/19 = 36.8% are valid integer ratios -> zero GRIM false positives!
    assert "GRIM_PERCENTAGE_INCONSISTENT" not in codes
    # 60 + 60 == 120 -> zero cohort drift false positives!
    assert "PROSE_VS_TABLE_N_DRIFT" not in codes
    # F(1, 20) = 4.35 has p = 0.050, violating p < 0.001!
    assert "INEQUALITY_PVALUE_VIOLATION" in codes


# Manuscript Preflight CI (`mpreflight`)

[![CI](https://github.com/cjprybol/manuscript-preflight-ci/actions/workflows/ci.yml/badge.svg)](https://github.com/cjprybol/manuscript-preflight-ci/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Preflight Pilot](https://img.shields.io/badge/pilot-early%20access-brightgreen)](https://cjprybol.github.io/app-portfolio-landing-pages/manuscript-preflight-ci/)

**Catch retracted citations, hallucinated `.bib` entries, `p`-value mismatches, and table-vs-prose sample-size (`N`) drift before Desk Review.**

`manuscript-preflight-ci` is a zero-dependency, local-first Python CLI and GitHub Action for scientific manuscripts written in LaTeX/Overleaf (`.tex`), Quarto (`.qmd`), Markdown (`.md`), and Word (`.docx`).

---

## The Real-World Problems It Catches

```text
[FAIL] ref:Lesne2006 (DOI 10.1038/nature04533)
       Notice: RetractionIn recorded via Crossref/PubMed (PMID:38914864, 2024-06-24).
       Cited in: Introduction, line 42 ("...established oligomer paradigm [14]")

[FAIL] ref:Hallucinated2024 (DOI 10.1093/bioinformatics/btab001)
       Bibliography title ('Quantum transformer scaling...') does not match
       Crossref metadata ('Fast alignment of metagenomic reads...'; token overlap=0%).

[WARN] Table 2 vs Results prose sample-size drift
       Prose line 88 states 'n = 142 evaluable patients', but Table 2 arm totals sum to 139 (71 + 68).

[WARN] GRIM granularity check (34.8% at N = 19)
       Reported 34.8% at N = 19 is not achievable from an integer count
       (nearest ratios: 6/19 = 31.6%, 7/19 = 36.8%).

[FAIL] t(20) = 1.50, p = 0.012
       Reported 't(20) = 1.50, p = 0.012', but recomputed p = 0.1492
       (crosses alpha=0.05 significance threshold).

[PASS] 64/65 bibliography references resolved cleanly (4 FAIL, 2 WARN).
```

- **100% Ephemeral & Pre-Submission Safe:** Runs locally on your workstation or private GitHub Actions runner. Unpublished manuscript prose is never uploaded to third-party servers, preserving confidentiality and `35 U.S.C. § 102` patent novelty.
- **Live Open Bibliographic Verification:** Queries live **Crossref** (including **Retraction Watch** `update-to` notices), **OpenAlex (CC0)**, and **NCBI PubMed E-utilities** by DOI/PMID only — reporting upstream notice types verbatim (`RetractionIn`, `ExpressionOfConcernIn`, `ErratumIn`) and catching title/DOI swaps without storing or redistributing copyrighted abstracts.
- **Deterministic Math & Table Reconciliation:**
  - **Table-vs-Prose Cohort `N` Drift:** Flags mismatches between prose cohort statements (`"n = 142 evaluable patients"`) and Markdown/LaTeX/DOCX table arm totals (`71 + 68 = 139`).
  - **GRIM Granularity Check:** Flags reported subgroup percentages mathematically impossible for integer counts at small sample sizes (`N < 100`).
  - **Inline Test-Statistic Recomputation:** Recomputes exact two-tailed `p`-values from inline `t`, `F`, `χ²`, `r`, and `z` statistics and flags `alpha = 0.05` decision flips.

---

## Quickstart

```bash
# Clone and install locally
git clone https://github.com/cjprybol/manuscript-preflight-ci.git
cd manuscript-preflight-ci
pip install .

# Run preflight check on LaTeX, Markdown, Quarto, or Word manuscripts
mpreflight check paper.tex --bib references.bib --output-md preflight-report.md
```

### GitHub Actions Integration

Drop this into `.github/workflows/manuscript-preflight.yml`:

```yaml
name: Manuscript Preflight CI
on: [push, pull_request]

jobs:
  preflight:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: cjprybol/manuscript-preflight-ci@main
        with:
          manuscript: manuscript/main.tex
          bib: manuscript/references.bib
          fail-on: fail
          output-markdown: preflight-report.md
```

---

## Supported Formats

| Format | Extension | Capabilities |
| :--- | :--- | :--- |
| **LaTeX / Overleaf** | `.tex` | `\cite{}`, `\citep{}`, `\citet{}`, tabular `&` arm headers, inline stats |
| **Quarto** | `.qmd` | `@cite_key`, markdown pipe tables, inline stats |
| **Pandoc Markdown** | `.md` | `@cite_key`, markdown tables, inline stats |
| **Microsoft Word** | `.docx` | Paragraph text, embedded XML tables, inline DOI/PMID citations |

---

## Open-Core Tiers & Pilot Access

- **Free Open-Source CLI (`oss-free`):** Unlimited local statistical, GRIM, and table-vs-prose `N` checks + up to `25` live bibliography verifications per run (`MIT` licensed).
- **7-Day Submission Pass (`$29`):** Unlimited bibliography size for 1 paper during submission week.
- **Pass + Reviewer Stress-Test (`$59`):** Adds zero-retention adversarial statistical review mapped to manuscript lines.
- **PI Lab CI Pack (`$199/yr`):** Unlimited GitHub Action / Quarto / CLI runs across all lab repositories; single annual university P-card charge without PO bureaucracy.
  - [Reserve pilot access on the landing page](https://cjprybol.github.io/app-portfolio-landing-pages/manuscript-preflight-ci/)

---

## Scope & Provenance Notice

Manuscript Preflight CI performs mechanical bibliographic metadata lookups (via Crossref, Retraction Watch, OpenAlex CC0, and NCBI PubMed E-utilities) and arithmetic consistency checks for author verification only. Flags reflect upstream registry statuses (`ErratumIn`, `ExpressionOfConcernIn`, `RetractionIn`) or rounding ambiguities and do not constitute academic-integrity findings, peer review, or legal determinations.

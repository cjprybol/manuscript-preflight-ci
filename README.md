# Manuscript Preflight CI (`mpreflight`)

**Catch retracted citations, hallucinated `.bib` entries, `p`-value mismatches, and table-vs-prose sample-size (`N`) drift before Desk Review.**

`manuscript-preflight-ci` is a zero-dependency, local-first Python CLI and GitHub Action for `.tex` (LaTeX/Overleaf), `.qmd` (Quarto), `.md`, and `.docx` manuscripts.

- **100% Ephemeral & Pre-Submission Safe:** Runs locally on your workstation or private GitHub Actions runner. Unpublished manuscript prose is never uploaded to third-party servers, preserving confidentiality and `35 U.S.C. § 102` patent novelty.
- **Live Open Bibliographic Verification:** Queries live **Crossref** (including **Retraction Watch** `update-to` notices), **OpenAlex (CC0)**, and **NCBI PubMed E-utilities** by DOI/PMID only — reporting upstream notice types verbatim (`RetractionIn`, `ExpressionOfConcernIn`, `ErratumIn`) and catching title/DOI swaps without storing or redistributing copyrighted abstracts.
- **Deterministic Math & Table Reconciliation:**
  - **Table-vs-Prose Cohort `N` Drift:** Flags mismatches between prose cohort statements (`"n = 142 evaluable patients"`) and Markdown/LaTeX/DOCX table arm totals (`71 + 68 = 139`).
  - **GRIM Granularity Check:** Flags reported subgroup percentages impossible for integer counts at small sample sizes (`N < 100`).
  - **Inline Test-Statistic Recomputation:** Recomputes exact two-tailed `p`-values from inline `t`, `F`, `χ²`, `r`, and `z` statistics and flags `alpha = 0.05` decision flips.

## Quickstart

```bash
pip install .
mpreflight check paper.tex --bib references.bib --output-md preflight-report.md
```

### GitHub Actions Usage

```yaml
- uses: cjprybol/manuscript-preflight-ci@v0.1.0
  with:
    manuscript: manuscript/main.tex
    bib: manuscript/refs.bib
    fail-on: fail
```

## Open-Core Tiers & Pilot Access

- **Free Open-Source CLI (`oss-free`):** Unlimited local statistical, GRIM, and table-vs-prose `N` checks + up to `25` live bibliography verifications per run (`MIT` licensed).
- **7-Day Submission Pass (`$29`) / Reviewer Stress-Test Pass (`$59`) / PI Lab CI Pack (`$199/yr` university P-card):** Unlimited bibliography size + multi-repo Lab CI + optional zero-retention adversarial reviewer stress-test.
  - Reserve pilot access: https://cjprybol.github.io/app-portfolio-landing-pages/manuscript-preflight-ci/

## Scope & Provenance Notice

Manuscript Preflight CI performs mechanical bibliographic metadata lookups (via Crossref, Retraction Watch, OpenAlex CC0, and NCBI PubMed E-utilities) and arithmetic consistency checks for author verification only. Flags reflect upstream registry statuses (`ErratumIn`, `ExpressionOfConcernIn`, `RetractionIn`) or rounding ambiguities and do not constitute academic-integrity findings, peer review, or legal determinations.

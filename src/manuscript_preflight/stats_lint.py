"""Deterministic statistical & cohort consistency checks (GRIM, statcheck p-values, table-vs-prose N)."""

from __future__ import annotations

import math
import re

from manuscript_preflight.ingest import ManuscriptDocument
from manuscript_preflight.models import PreflightFinding


# ---------------------------------------------------------------------------
# Pure-Python Exact Special Functions (Regularized Incomplete Beta & Gamma)
# ---------------------------------------------------------------------------


def _betacf(a: float, b: float, x: float, max_iter: int = 200, eps: float = 3e-14) -> float:
    """Modified Lentz continued fraction for regularized incomplete beta I_x(a, b)."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    """Compute I_x(a, b) for 0 <= x <= 1."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(a * math.log(x) + b * math.log(1.0 - x) - lbeta)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def regularized_upper_gamma(a: float, x: float, max_iter: int = 200, eps: float = 3e-14) -> float:
    """Compute Q(a, x) = 1 - P(a, x) for a > 0, x >= 0."""
    if x <= 0.0:
        return 1.0
    gln = math.lgamma(a)
    if x < a + 1.0:
        ap = a
        total = 1.0 / a
        delta = total
        for _ in range(max_iter):
            ap += 1.0
            delta *= x / ap
            total += delta
            if abs(delta) < abs(total) * eps:
                break
        p_val = total * math.exp(-x + a * math.log(x) - gln)
        return max(0.0, min(1.0, 1.0 - p_val))

    b = x + 1.0 - a
    c = 1.0 / 1e-30
    d = 1.0 / b
    h = d
    for i in range(1, max_iter + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < 1e-30:
            d = 1e-30
        c = b + an / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return max(0.0, min(1.0, math.exp(-x + a * math.log(x) - gln) * h))


def two_tailed_t_pvalue(t_stat: float, df: float) -> float:
    """Exact two-tailed p-value for Student's t distribution."""
    if df <= 0:
        return float("nan")
    x = df / (df + t_stat * t_stat)
    return regularized_incomplete_beta(0.5 * df, 0.5, x)


def f_pvalue(f_stat: float, df1: float, df2: float) -> float:
    """Exact upper-tail p-value for F(df1, df2)."""
    if df1 <= 0 or df2 <= 0 or f_stat < 0:
        return float("nan")
    if f_stat == 0.0:
        return 1.0
    x = df2 / (df2 + df1 * f_stat)
    return regularized_incomplete_beta(0.5 * df2, 0.5 * df1, x)


def chi2_pvalue(chi2_stat: float, df: float) -> float:
    """Exact upper-tail p-value for chi-square(df)."""
    if df <= 0 or chi2_stat < 0:
        return float("nan")
    return regularized_upper_gamma(0.5 * df, 0.5 * chi2_stat)


def two_tailed_z_pvalue(z_stat: float) -> float:
    """Exact two-tailed standard normal p-value."""
    return math.erfc(abs(z_stat) / math.sqrt(2.0))


def two_tailed_r_pvalue(r_stat: float, df: float) -> float:
    """Exact two-tailed p-value for Pearson correlation r with df = N - 2."""
    if df <= 0 or abs(r_stat) > 1.0:
        return float("nan")
    if abs(r_stat) == 1.0:
        return 0.0
    t_val = abs(r_stat) * math.sqrt(df / (1.0 - r_stat * r_stat))
    return two_tailed_t_pvalue(t_val, df)


# ---------------------------------------------------------------------------
# 1. GRIM Percentage & Integer-Scale Mean Granularity Checks
# ---------------------------------------------------------------------------

_PCT_WITH_N_RE = re.compile(
    r"\b(\d{1,2}\.\d{1,3})\s*%\s*(?:of\s+)?\(\s*[nN]\s*=\s*(\d{2,4})\s*\)"
    r"|\b(\d{1,2}\.\d{1,3})\s*%\s+at\s+(?:subgroup\s+)?[nN]\s*=\s*(\d{2,4})\b"
)


def check_grim_percentages(doc: ManuscriptDocument) -> list[PreflightFinding]:
    """Flag reported percentages impossible for integer numerator counts k / N."""
    findings: list[PreflightFinding] = []
    for idx, line in enumerate(doc.lines, start=1):
        for match in _PCT_WITH_N_RE.finditer(line):
            pct_str = match.group(1) or match.group(3)
            n_str = match.group(2) or match.group(4)
            if not pct_str or not n_str:
                continue
            decimals = len(pct_str.split(".")[1])
            n_val = int(n_str)
            # GRIM percentage resolution applies when N < 10^(decimals + 2) / 2
            if n_val <= 0 or n_val >= (10 ** (decimals + 1)):
                continue
            reported = float(pct_str)
            achievable = [round(100.0 * k / n_val, decimals) for k in range(n_val + 1)]
            # Allow half-ulp rounding ambiguity (round-half-up vs bankers rounding)
            tol = 0.51 * (10.0 ** (-decimals))
            if any(abs(reported - cand) <= tol for cand in achievable):
                continue

            k_low = max(0, min(n_val, math.floor(reported * n_val / 100.0)))
            k_high = min(n_val, k_low + 1)
            low_pct = round(100.0 * k_low / n_val, decimals)
            high_pct = round(100.0 * k_high / n_val, decimals)
            findings.append(
                PreflightFinding(
                    severity="WARN",
                    category="grim_granularity",
                    code="GRIM_PERCENTAGE_INCONSISTENT",
                    subject=f"GRIM granularity check ({pct_str}% at N = {n_val})",
                    message=(
                        f"Reported {pct_str}% at N = {n_val} is not achievable from an integer count "
                        f"(nearest ratios: {k_low}/{n_val} = {low_pct:.{decimals}f}%, "
                        f"{k_high}/{n_val} = {high_pct:.{decimals}f}%)."
                    ),
                    location=f"line {idx}",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# 2. Inline Test-Statistic vs Reported p-Value Verification (statcheck)
# ---------------------------------------------------------------------------

_STAT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "t",
        re.compile(
            r"\bt\s*\(\s*(\d+(?:\.\d+)?)\s*\)\s*=\s*([+-]?\d+(?:\.\d+)?)\s*,\s*p\s*([=<>])\s*(0?\.\d+|\d\.\d+e-\d+)",
            re.IGNORECASE,
        ),
    ),
    (
        "F",
        re.compile(
            r"\bF\s*\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\)\s*=\s*(\d+(?:\.\d+)?)\s*,\s*p\s*([=<>])\s*(0?\.\d+|\d\.\d+e-\d+)",
            re.IGNORECASE,
        ),
    ),
    (
        "chi2",
        re.compile(
            r"(?:\bchi2|\bchi-square|χ²|χ\^2|\\chi\^2)\s*\(\s*(\d+(?:\.\d+)?)(?:\s*,\s*[nN]\s*=\s*\d+)?\s*\)\s*=\s*(\d+(?:\.\d+)?)\s*,\s*p\s*([=<>])\s*(0?\.\d+|\d\.\d+e-\d+)",
            re.IGNORECASE,
        ),
    ),
    (
        "r",
        re.compile(
            r"\br\s*\(\s*(\d+)\s*\)\s*=\s*([+-]?0?\.\d+)\s*,\s*p\s*([=<>])\s*(0?\.\d+|\d\.\d+e-\d+)",
            re.IGNORECASE,
        ),
    ),
    (
        "z",
        re.compile(
            r"\bz\s*=\s*([+-]?\d+(?:\.\d+)?)\s*,\s*p\s*([=<>])\s*(0?\.\d+|\d\.\d+e-\d+)",
            re.IGNORECASE,
        ),
    ),
)


def check_inline_test_statistics(
    doc: ManuscriptDocument, *, alpha: float = 0.05
) -> list[PreflightFinding]:
    """Recompute two-tailed p-values from inline t, F, chi2, r, and z statistics."""
    findings: list[PreflightFinding] = []
    for idx, line in enumerate(doc.lines, start=1):
        for kind, pat in _STAT_PATTERNS:
            for m in pat.finditer(line):
                raw_expr = m.group(0)
                if kind == "t":
                    df = float(m.group(1))
                    stat = float(m.group(2))
                    op, p_str = m.group(3), m.group(4)
                    recomputed = two_tailed_t_pvalue(stat, df)
                elif kind == "F":
                    df1, df2 = float(m.group(1)), float(m.group(2))
                    stat = float(m.group(3))
                    op, p_str = m.group(4), m.group(5)
                    recomputed = f_pvalue(stat, df1, df2)
                elif kind == "chi2":
                    df = float(m.group(1))
                    stat = float(m.group(2))
                    op, p_str = m.group(3), m.group(4)
                    recomputed = chi2_pvalue(stat, df)
                elif kind == "r":
                    df = float(m.group(1))
                    stat = float(m.group(2))
                    op, p_str = m.group(3), m.group(4)
                    recomputed = two_tailed_r_pvalue(stat, df)
                else:
                    stat = float(m.group(1))
                    op, p_str = m.group(2), m.group(3)
                    recomputed = two_tailed_z_pvalue(stat)

                if math.isnan(recomputed):
                    continue
                reported_p = float(p_str)
                decimals = len(p_str.split(".")[1]) if "." in p_str and "e" not in p_str.lower() else 4
                round_tol = max(0.002, 1.5 * (10.0 ** (-decimals)))

                # Check decision-threshold flip around alpha = 0.05
                reported_sig = (reported_p < alpha) or (op == "<" and reported_p <= alpha)
                recomputed_sig = recomputed < alpha

                if op == "=" and abs(recomputed - reported_p) > round_tol:
                    sev = "FAIL" if reported_sig != recomputed_sig else "WARN"
                    findings.append(
                        PreflightFinding(
                            severity=sev,  # type: ignore[arg-type]
                            category="statcheck_pvalue",
                            code="DECISION_PVALUE_FLIP" if sev == "FAIL" else "PVALUE_ROUNDING_DRIFT",
                            subject=raw_expr,
                            message=(
                                f"Reported '{raw_expr}', but recomputed p = {recomputed:.4g} "
                                f"({'crosses alpha=0.05 significance threshold' if sev == 'FAIL' else 'exceeds rounding tolerance'})."
                            ),
                            location=f"line {idx}",
                        )
                    )
                elif op == "<" and recomputed > reported_p + round_tol:
                    sev = "FAIL" if reported_sig != recomputed_sig else "WARN"
                    findings.append(
                        PreflightFinding(
                            severity=sev,  # type: ignore[arg-type]
                            category="statcheck_pvalue",
                            code="INEQUALITY_PVALUE_VIOLATION",
                            subject=raw_expr,
                            message=(
                                f"Reported '{raw_expr}', but recomputed p = {recomputed:.4g} exceeds stated bound {reported_p}."
                            ),
                            location=f"line {idx}",
                        )
                    )
    return findings


# ---------------------------------------------------------------------------
# 3. Table-vs-Prose Cohort Sample-Size (N) Reconciliation
# ---------------------------------------------------------------------------

_PROSE_COHORT_N_RE = re.compile(
    r"\b[nN]\s*=\s*(\d{2,6})\s+(?:evaluable\s+|enrolled\s+|randomized\s+|total\s+|eligible\s+)?"
    r"(?:patients|participants|subjects|samples|adults|cases|mice|cohorts)\b"
)


def check_cohort_sample_drift(doc: ManuscriptDocument) -> list[PreflightFinding]:
    """Reconcile prose cohort N declarations against table arm totals."""
    findings: list[PreflightFinding] = []
    if not doc.tables:
        return findings

    prose_counts: list[tuple[int, int, str]] = []
    for idx, line in enumerate(doc.lines, start=1):
        if line.strip().startswith("|") or "&" in line:
            continue
        for m in _PROSE_COHORT_N_RE.finditer(line):
            prose_counts.append((int(m.group(1)), idx, m.group(0)))

    for tbl in doc.tables:
        arm_str = " + ".join(str(c) for c in tbl.arm_counts)
        if tbl.stated_total is not None and tbl.stated_total != tbl.arm_sum:
            findings.append(
                PreflightFinding(
                    severity="FAIL",
                    category="cohort_sample_drift",
                    code="TABLE_INTERNAL_SUM_MISMATCH",
                    subject=f"{tbl.label} internal total mismatch",
                    message=(
                        f"{tbl.label} header states total N = {tbl.stated_total}, "
                        f"but arm counts sum to {tbl.arm_sum} ({arm_str})."
                    ),
                    location=f"line {tbl.line_number}",
                )
            )
            continue

        for prose_n, prose_line, prose_phrase in prose_counts:
            # Flag close cohort drift (within 15% of arm_sum but unequal)
            diff = abs(prose_n - tbl.arm_sum)
            if 0 < diff <= max(3, int(0.15 * prose_n)):
                findings.append(
                    PreflightFinding(
                        severity="WARN",
                        category="cohort_sample_drift",
                        code="PROSE_VS_TABLE_N_DRIFT",
                        subject=f"{tbl.label} vs prose sample-size drift",
                        message=(
                            f"Prose (line {prose_line}) states '{prose_phrase}' (N = {prose_n}), "
                            f"but {tbl.label} arm totals sum to {tbl.arm_sum} ({arm_str})."
                        ),
                        location=f"line {prose_line} / {tbl.label} (line {tbl.line_number})",
                    )
                )
                break

    return findings

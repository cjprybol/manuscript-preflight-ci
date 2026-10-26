"""Ephemeral local parsers for .bib, .tex, .qmd/.md, and .docx manuscripts."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

from manuscript_preflight.models import BibEntry, TableCohort

_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)\b")
_PMID_RE = re.compile(r"\bPMID\s*[:#]?\s*(\d{5,9})\b", re.IGNORECASE)
_BIB_ENTRY_START_RE = re.compile(r"@([A-Za-z]+)\s*\{\s*([^,\s]+)\s*,", re.MULTILINE)
_BIB_FIELD_RE = re.compile(
    r"([A-Za-z0-9_-]+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"[^\"]*\"|\d+)",
    re.DOTALL,
)
_LATEX_CITE_RE = re.compile(r"\\cite[a-zA-Z*]*\{([^}]+)\}")
_PANDOC_CITE_RE = re.compile(r"@([A-Za-z0-9_:.#$%&\-+?<>~/]+)")


@dataclass(frozen=True)
class ManuscriptDocument:
    """In-memory representation of a local manuscript (never persisted)."""

    path: Path
    lines: tuple[str, ...]
    tables: tuple[TableCohort, ...]
    inline_refs: tuple[BibEntry, ...]
    citation_contexts: dict[str, tuple[str, ...]]

    @property
    def full_text(self) -> str:
        return "\n".join(self.lines)


def clean_doi(raw: str) -> str:
    """Normalize DOI string by stripping URL prefixes and trailing punctuation."""
    val = raw.strip()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
        "DOI:",
    ):
        if val.startswith(prefix):
            val = val[len(prefix) :].strip()
    return val.rstrip(".,;)]}>\"'")


def parse_bibtex(text: str, source_name: str = "") -> list[BibEntry]:
    """Parse BibTeX entries deterministically without external dependencies."""
    entries: list[BibEntry] = []
    starts = list(_BIB_ENTRY_START_RE.finditer(text))
    for idx, match in enumerate(starts):
        entry_type = match.group(1).lower()
        if entry_type in {"comment", "preamble", "string"}:
            continue
        key = match.group(2).strip()
        body_start = match.end()
        body_end = starts[idx + 1].start() if idx + 1 < len(starts) else len(text)
        body = text[body_start:body_end]

        fields: dict[str, str] = {}
        for fmatch in _BIB_FIELD_RE.finditer(body):
            fname = fmatch.group(1).lower()
            fval = fmatch.group(2).strip()
            if (fval.startswith("{") and fval.endswith("}")) or (
                fval.startswith('"') and fval.endswith('"')
            ):
                fval = fval[1:-1]
            fval = re.sub(r"[{}]", "", " ".join(fval.split()))
            fields[fname] = fval

        doi_val = fields.get("doi")
        if not doi_val and "url" in fields:
            m_doi = _DOI_RE.search(fields["url"])
            if m_doi:
                doi_val = m_doi.group(1)
        pmid_val = fields.get("pmid") or fields.get("eprint")
        if pmid_val and not pmid_val.isdigit():
            pmid_val = None

        entries.append(
            BibEntry(
                key=key,
                entry_type=entry_type,
                title=fields.get("title", ""),
                year=fields.get("year", ""),
                doi=clean_doi(doi_val) if doi_val else None,
                pmid=pmid_val,
                raw_source=source_name,
            )
        )
    return entries


def _extract_docx_lines_and_tables(path: Path) -> tuple[list[str], list[TableCohort]]:
    """Extract paragraph text and table arm counts from .docx XML in memory."""
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    lines: list[str] = []
    tables: list[TableCohort] = []
    with zipfile.ZipFile(path, "r") as zf:
        if "word/document.xml" not in zf.namelist():
            return [], []
        xml_bytes = zf.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    body = root.find("w:body", ns)
    if body is None:
        return [], []

    tbl_idx = 0
    for child in body:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            txt = "".join(t.text or "" for t in child.findall(".//w:t", ns)).strip()
            if txt:
                lines.append(txt)
        elif tag == "tbl":
            tbl_idx += 1
            rows_text: list[list[str]] = []
            for row in child.findall("w:tr", ns):
                cells: list[str] = []
                for cell in row.findall("w:tc", ns):
                    ctxt = "".join(
                        t.text or "" for t in cell.findall(".//w:t", ns)
                    ).strip()
                    cells.append(ctxt)
                if any(cells):
                    rows_text.append(cells)
                    lines.append(" | ".join(cells))
            cohort = _parse_table_rows(
                rows_text, label=f"Table {tbl_idx}", line_number=len(lines)
            )
            if cohort is not None:
                tables.append(cohort)
    return lines, tables


_HEADER_N_RE = re.compile(r"\(\s*[nN]\s*=\s*(\d{1,6})\s*\)")
_TOTAL_N_RE = re.compile(
    r"(?:total|overall|all\s+patients|combined)[^0-9]{0,20}[nN]\s*=\s*(\d{1,6})",
    re.IGNORECASE,
)


def _parse_table_rows(
    rows: list[list[str]], *, label: str, line_number: int
) -> TableCohort | None:
    """Extract arm sample counts like 'Arm A (n = 71) | Arm B (n = 68)' from table headers."""
    if not rows:
        return None
    for row in rows[:3]:
        joined = " | ".join(row)
        stated_total: int | None = None
        m_tot = _TOTAL_N_RE.search(joined)
        if m_tot:
            stated_total = int(m_tot.group(1))
        arm_counts: list[int] = []
        for cell in row:
            if re.search(r"\b(?:total|overall|all)\b", cell, re.IGNORECASE):
                m_c = _HEADER_N_RE.search(cell)
                if m_c and stated_total is None:
                    stated_total = int(m_c.group(1))
                continue
            m_arm = _HEADER_N_RE.search(cell)
            if m_arm:
                arm_counts.append(int(m_arm.group(1)))
        if len(arm_counts) >= 2:
            return TableCohort(
                label=label,
                arm_counts=tuple(arm_counts),
                stated_total=stated_total,
                line_number=line_number,
            )
    return None


def _extract_markdown_and_latex_tables(lines: list[str]) -> list[TableCohort]:
    """Extract TableCohort blocks from Markdown pipe tables and LaTeX tabular headers."""
    cohorts: list[TableCohort] = []
    tbl_counter = 0
    current_label: str | None = None
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m_cap = re.search(r"\b(Table\s+\d+)\b", line, re.IGNORECASE)
        if m_cap:
            current_label = m_cap.group(1).title()

        # Markdown pipe table
        if line.startswith("|") and line.endswith("|") and line.count("|") >= 3:
            block: list[list[str]] = []
            start_line = i + 1
            while (
                i < len(lines)
                and lines[i].strip().startswith("|")
                and lines[i].strip().endswith("|")
            ):
                cells = [c.strip() for c in lines[i].strip()[1:-1].split("|")]
                if not all(re.fullmatch(r"[-:\s]*", c) for c in cells):
                    block.append(cells)
                i += 1
            tbl_counter += 1
            lbl = current_label or f"Table {tbl_counter}"
            parsed = _parse_table_rows(block, label=lbl, line_number=start_line)
            if parsed is not None:
                cohorts.append(parsed)
                current_label = None
            continue

        # LaTeX tabular row with '&' and multiple (n = X)
        if "&" in line and len(_HEADER_N_RE.findall(line)) >= 2:
            clean_row = re.sub(r"\\\\.*$", "", line)
            cells = [c.strip() for c in clean_row.split("&")]
            tbl_counter += 1
            lbl = current_label or f"Table {tbl_counter}"
            parsed = _parse_table_rows([cells], label=lbl, line_number=i + 1)
            if parsed is not None:
                cohorts.append(parsed)
                current_label = None
        i += 1
    return cohorts


def load_manuscript(path: Path) -> ManuscriptDocument:
    """Load a local .tex, .qmd, .md, or .docx manuscript into memory."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        lines, tables = _extract_docx_lines_and_tables(path)
    else:
        raw = path.read_text(encoding="utf-8")
        lines = raw.splitlines()
        tables = _extract_markdown_and_latex_tables(lines)

    contexts: dict[str, list[str]] = {}
    inline_refs: list[BibEntry] = []
    seen_inline_ids: set[str] = set()

    for idx, line in enumerate(lines, start=1):
        loc = f"line {idx}"
        for m_lat in _LATEX_CITE_RE.finditer(line):
            for key in (k.strip() for k in m_lat.group(1).split(",") if k.strip()):
                contexts.setdefault(key, []).append(loc)
        for m_pan in _PANDOC_CITE_RE.finditer(line):
            key = m_pan.group(1).rstrip(".,;:)]")
            if not key or "@" in key or "." in key and key.endswith((".edu", ".com", ".org")):
                continue
            contexts.setdefault(key, []).append(loc)
        for m_doi in _DOI_RE.finditer(line):
            doi = clean_doi(m_doi.group(1))
            if doi not in seen_inline_ids:
                seen_inline_ids.add(doi)
                inline_refs.append(
                    BibEntry(
                        key=f"inline_doi_{len(inline_refs) + 1}",
                        doi=doi,
                        raw_source=f"{path.name}:{idx}",
                    )
                )
            contexts.setdefault(doi, []).append(loc)
        for m_pmid in _PMID_RE.finditer(line):
            pmid = m_pmid.group(1)
            if f"pmid:{pmid}" not in seen_inline_ids:
                seen_inline_ids.add(f"pmid:{pmid}")
                inline_refs.append(
                    BibEntry(
                        key=f"inline_pmid_{pmid}",
                        pmid=pmid,
                        raw_source=f"{path.name}:{idx}",
                    )
                )
            contexts.setdefault(f"PMID:{pmid}", []).append(loc)

    return ManuscriptDocument(
        path=path,
        lines=tuple(lines),
        tables=tuple(tables),
        inline_refs=tuple(inline_refs),
        citation_contexts={k: tuple(v) for k, v in contexts.items()},
    )

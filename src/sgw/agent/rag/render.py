"""Render a corpus document as a reader sees it: title block, control box, SUPERSEDED line, Revision Summary,
paginated body with running header, footer and "Page n of N".

The renderer also keeps the logical structure (blocks with their section and page) so the chunker can split
on sections and cite pages without re-parsing the rendered text.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field

from sgw.agent.rag.corpus import OWNER_MANUALS, Document

WIDTH = 96
PAGE_LINES = 54
UNCONTROLLED = "Printed copies are uncontrolled. Confirm the current revision in DocCtl before use."
PAGEBREAK = "<<PAGEBREAK>>"
FUNCTION_NAMES = {
    "command": "Emergency Management",
    "operations": "Distribution Operations",
    "planning": "Storm Planning",
    "logistics": "Supply Chain and Logistics",
    "water_operations": "Water Distribution",
    "compliance": "Water Quality and Compliance",
    "communications": "Corporate Communications",
    "transmission": "Transmission Operations",
}
SUPERSEDED_RE = re.compile(r"Rev\s+(?P<rev>[A-Z](?:/\d+)?)\s*\(eff\.\s*(?P<date>\d{4}-\d{2}-\d{2})\)")


@dataclass
class Block:
    section: str
    kind: str
    lines: list[str]
    page: int = 0

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class RenderedDoc:
    doc: Document
    blocks: list[Block]
    pages: list[list[str]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\f\n".join("\n".join(p) + "\n" for p in self.pages)

    @property
    def page_count(self) -> int:
        return len(self.pages)


def superseded_line(doc: Document) -> str | None:
    if not doc.superseded_by:
        return None
    m = SUPERSEDED_RE.search(doc.superseded_by)
    if not m:
        return f"SUPERSEDED by {doc.superseded_by}. Retained for record."
    rev = m["rev"].split("/")[0]
    return f"SUPERSEDED by Rev {rev}, {m['date']}. Retained for record."


def _wrap(line: str, width: int = WIDTH) -> list[str]:
    if len(line) <= width:
        return [line]
    indent = len(line) - len(line.lstrip(" "))
    hang = indent
    m = re.match(r"^(\s*(?:\d+(?:\.\d+)+|[a-z]\.|\(\d+\)|\[ \]|NOTE:|CAUTION:)\s+)", line)
    if m:
        hang = len(m.group(1))
    return textwrap.wrap(
        line.strip(),
        width=width,
        initial_indent=" " * indent,
        subsequent_indent=" " * hang,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [line]


def _table(rows: list[list[str]], width: int = WIDTH) -> list[str]:
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    natural = [max(len(r[c]) for r in rows) for c in range(ncol)]
    budget = width - (3 * ncol + 1)
    floor = [max([3] + [len(tok) for r in rows for tok in r[c].split()]) for c in range(ncol)]
    widths = [max(3, w) for w in natural]
    while sum(widths) > budget:
        shrinkable = [i for i in range(ncol) if widths[i] > max(floor[i], 8)]
        if not shrinkable:
            break
        i = max(shrinkable, key=lambda j: widths[j])
        widths[i] -= 1
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out = [sep]
    for idx, row in enumerate(rows):
        cells = [
            textwrap.wrap(cell, w, break_long_words=False, break_on_hyphens=False) or [""]
            for cell, w in zip(row, widths, strict=True)
        ]
        height = max(len(c) for c in cells)
        for k in range(height):
            parts = [(c[k] if k < len(c) else "").ljust(w) for c, w in zip(cells, widths, strict=True)]
            out.append("| " + " | ".join(parts) + " |")
        if idx == 0:
            out.append(sep.replace("-", "="))
    out.append(sep)
    return out


def _split_cells(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def _is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?", line.strip()))


ITEM_START = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s|[a-z]\.\s|\([a-z0-9]+\)\s|NOTE\b|CAUTION\b|WARNING\b|\[[ xX]\]|•"
    r"|[A-Z][A-Za-z0-9 /&()'-]{0,48}:(?:\s|$)|[A-Z0-9][A-Z0-9 ,/&()'-]{3,}$|TLP:|<<)"
)


def _continues(line: str) -> bool:
    """A hard-wrapped continuation of the previous line (not blank, not a heading, table or new item)."""
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", "|")) or stripped == PAGEBREAK:
        return False
    return not ITEM_START.match(line)


def body_blocks(body: str) -> list[Block]:
    blocks: list[Block] = []
    section = ""
    lines = body.split("\n")
    i = 0
    while i < len(lines):
        raw = lines[i].rstrip()
        if not raw.strip():
            i += 1
            continue
        if raw.strip() == PAGEBREAK:
            blocks.append(Block(section, "pagebreak", []))
            i += 1
            continue
        if raw.startswith("## ") or raw.startswith("# "):
            level = 2 if raw.startswith("## ") else 1
            heading = raw[level + 1 :].strip()
            section = (
                heading if level == 1 else f"{section.split(' > ')[0]} > {heading}" if section else heading
            )
            blocks.append(Block(section, "heading", [heading]))
            i += 1
            continue
        if raw.lstrip().startswith("|"):
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                if not _is_separator(lines[i]):
                    rows.append(_split_cells(lines[i]))
                i += 1
            blocks.append(Block(section, "table", _table(rows)))
            continue
        text = raw
        i += 1
        while i < len(lines) and _continues(lines[i]):
            text = f"{text.rstrip()} {lines[i].strip()}"
            i += 1
        blocks.append(Block(section, "line", _wrap(text)))
    return blocks


def _box(pairs: list[tuple[str, str]], width: int = WIDTH) -> list[str]:
    inner = width - 4
    out = ["+" + "-" * (width - 2) + "+"]
    for label, value in pairs:
        text = f"{label}: {value}" if label else value
        for part in textwrap.wrap(text, inner, subsequent_indent="    ") or [""]:
            out.append("| " + part.ljust(inner) + " |")
    out.append("+" + "-" * (width - 2) + "+")
    return out


def front_blocks(doc: Document) -> list[Block]:
    sec = "Control box"
    manual = doc.manual
    owner = OWNER_MANUALS.get(manual or "", FUNCTION_NAMES.get(doc.owner_function, "SGW"))
    blocks: list[Block] = []
    if doc.layout == "record":
        top = f"{doc.classification}".ljust(WIDTH - len(doc.doc_id)) + doc.doc_id
        head = [top, "", "SGW", doc.title]
        if doc.origin == "federal":
            head = [top, "", doc.title]
        head.append(
            f"Date: {doc.effective.isoformat()}"
            + (f"   Expires: {doc.expires.isoformat()}" if doc.expires else "")
        )
        blocks.append(Block(sec, "title", head))
        return blocks
    left = f"SGW  {owner.upper()} MANUAL" if manual else f"SGW  {owner.upper()}"
    ident = doc.citation_id + (f"  (formerly {doc.legacy_id})" if doc.legacy_id else "")
    title = [left, "", ident, doc.title.upper()]
    banner = superseded_line(doc)
    if banner:
        title += ["", banner]
    blocks.append(Block(sec, "title", title))
    pairs: list[tuple[str, str]] = [
        ("Document", ident),
        ("Effective", doc.effective.isoformat()),
    ]
    if doc.supersedes:
        pairs.append(("Supersedes", doc.supersedes))
    if doc.expires:
        pairs.append(("Expires", doc.expires.isoformat()))
    pairs.append(("Owner", FUNCTION_NAMES.get(doc.owner_function, doc.owner_function)))
    if doc.sme:
        pairs.append(("Subject Matter Expert", doc.sme))
    if doc.next_review:
        pairs.append(("Periodic review due", doc.next_review.isoformat()))
    pairs.append(("Classification", doc.classification))
    for a in doc.approvals:
        pairs.append(("Approved", f"{a.position}, {a.name}, {a.date.isoformat()}"))
    if doc.states:
        pairs.append(("Applies to", ", ".join(doc.states) + " systems"))
    blocks.append(Block(sec, "box", _box(pairs)))
    if doc.changes:
        rows = [["Rev", "Date", "Section", "Change"]] + [
            [c.rev, c.date.isoformat(), c.section, c.change] for c in doc.changes
        ]
        blocks.append(Block("Revision Summary", "heading", ["REVISION SUMMARY"]))
        blocks.append(Block("Revision Summary", "table", _table(rows)))
    return blocks


def running_header(doc: Document) -> str:
    left = f"SGW | {doc.doc_id} {doc.title}"
    right = f"Rev {doc.revision_label}" if doc.revision_label else doc.effective.isoformat()
    room = WIDTH - len(right) - 1
    if len(left) > room:
        left = left[: room - 3].rstrip() + "..."
    return left.ljust(WIDTH - len(right)) + right


def footer(doc: Document, page: int, total: int) -> str:
    return f"{doc.citation_id} | {doc.classification} | Page {page} of {total}"


def render(doc: Document) -> RenderedDoc:
    blocks = front_blocks(doc) + body_blocks(doc.body)
    body_room = PAGE_LINES - 4
    pages_body: list[list[str]] = [[]]
    for block in blocks:
        if block.kind == "pagebreak":
            if pages_body[-1]:
                pages_body.append([])
            continue
        page = pages_body[-1]
        need = len(block.lines) + (1 if page else 0)
        if block.kind == "heading":
            need += 3
        if page and len(page) + need > body_room and len(block.lines) <= body_room:
            pages_body.append([])
            page = pages_body[-1]
        if page:
            page.append("")
        block.page = len(pages_body)
        for line in block.lines:
            if len(page) >= body_room:
                pages_body.append([])
                page = pages_body[-1]
            page.append(line)
    total = len(pages_body)
    pages: list[list[str]] = []
    for n, body in enumerate(pages_body, start=1):
        lines = ([running_header(doc), ""] if n > 1 else []) + body
        if n == total and doc.layout == "controlled":
            lines += ["", UNCONTROLLED]
        lines += ["", footer(doc, n, total)]
        pages.append(lines)
    return RenderedDoc(doc=doc, blocks=[b for b in blocks if b.kind != "pagebreak"], pages=pages)

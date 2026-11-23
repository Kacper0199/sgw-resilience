"""Prose lint for SGW LaTeX documents.

Strips LaTeX markup that is not prose (preamble, comments, TikZ, math, labels,
number macros, column specs), then checks the remaining text against
rules.yaml, the digit rule and the plain-language lexicon.

    uv run python docs/latex/lint/prose_lint.py docs/latex/briefing/briefing.tex --lexicon enforced

Set SGW_DENYLIST to a file kept outside the repository (one term per line) to
also fail on private names that must never reach a deliverable.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent

BLOCK_ENVS = ("tikzpicture", "verbatim", "lstlisting", "comment", "equation", "equation*", "align", "align*")
TABLE_ENVS = (
    "tabular",
    "tabular*",
    "tabularx",
    "longtable",
    "array",
    "minipage",
    "column",
    "columns",
    "xltabular",
)
STRIP_ALL = {
    "label",
    "ref",
    "eqref",
    "pageref",
    "autoref",
    "cref",
    "Cref",
    "cite",
    "citet",
    "citep",
    "citeauthor",
    "nocite",
    "input",
    "include",
    "includegraphics",
    "sgwnum",
    "sgwnumL",
    "sgwval",
    "sgwunit",
    "sgwlbl",
    "sgwmark",
    "url",
    "hypersetup",
    "setlength",
    "addtolength",
    "vspace",
    "hspace",
    "rule",
    "bibliography",
    "bibliographystyle",
    "setcounter",
    "rowcolor",
    "cellcolor",
    "arrayrulecolor",
    "specialrule",
    "cline",
    "cmidrule",
    "newcommand",
    "renewcommand",
    "providecommand",
    "def",
    "usepackage",
    "documentclass",
    "usetheme",
    "setbeamercolor",
    "setbeamertemplate",
    "definecolor",
    "color",
    "textcolor",
    "fontsize",
    "column",
    "sgwfit",
    "sgwstubnum",
    "sgwdefnum",
    "scalebox",
    "raisebox",
    "makebox",
    "parbox",
    "colorbox",
    "fcolorbox",
}
STRIP_FIRST = {
    "href": 1,
    "sgwsection": 2,
    "resizebox": 2,
    "sgwkpi": 2,
    "multicolumn": 2,
    "textcolor": 1,
    "multirow": 2,
    "sgwbudgetnote": 1,
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    severity: str
    match: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.severity}: [{self.rule}] '{self.match}': {self.message}"


def load_config() -> tuple[list[dict], list[re.Pattern], list[dict]]:
    rules_doc = yaml.safe_load((HERE / "rules.yaml").read_text(encoding="utf-8"))
    lexicon_doc = yaml.safe_load((HERE / "lexicon.yaml").read_text(encoding="utf-8"))
    rules = []
    for r in rules_doc["rules"]:
        flags = re.I if r.get("case") == "insensitive" else 0
        rules.append({**r, "regex": re.compile(r["pattern"], flags)})
    allow = [re.compile(p, re.I) for p in rules_doc["digit_allow"]]
    lexicon = [{**t, "regex": re.compile(t["term"])} for t in lexicon_doc["terms"]]
    return rules, allow, lexicon


def _blank(text: str, start: int, end: int) -> str:
    chunk = text[start:end]
    return text[:start] + re.sub(r"[^\n]", " ", chunk) + text[end:]


def _group_end(text: str, i: int, open_ch: str, close_ch: str) -> int:
    depth = 0
    for j in range(i, len(text)):
        c = text[j]
        if c == "\\":
            continue
        if c == open_ch and (j == 0 or text[j - 1] != "\\"):
            depth += 1
        elif c == close_ch and text[j - 1] != "\\":
            depth -= 1
            if depth == 0:
                return j + 1
    return len(text)


def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t":
        i += 1
    return i


def strip_latex(source: str) -> str:
    """Return text of the same line structure in which only prose is left."""
    text = re.sub(r"(?<!\\)%[^\n]*", "", source)
    begin = text.find("\\begin{document}")
    if begin >= 0:
        text = _blank(text, 0, begin + len("\\begin{document}"))
    for env in BLOCK_ENVS:
        pattern = re.compile(r"\\begin\{" + re.escape(env) + r"\}.*?\\end\{" + re.escape(env) + r"\}", re.S)
        while m := pattern.search(text):
            text = _blank(text, m.start(), m.end())
    while m := re.search(r"(?<!\\)\$.*?(?<!\\)\$", text, re.S):
        text = _blank(text, m.start(), m.end())
    text = re.sub(r"\\\\(\[[^\]]*\])?", "  ", text)

    out = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text) and text[i + 1].isalpha():
            m = re.match(r"\\([A-Za-z@]+)\*?", text[i:])
            name = m.group(1)
            j = i + m.end()
            strip_n = None
            keep_args = True
            if name in ("begin", "end"):
                k = _skip_ws(text, j)
                env_end = _group_end(text, k, "{", "}") if k < len(text) and text[k] == "{" else k
                env = text[k + 1 : env_end - 1]
                j = env_end
                if env in TABLE_ENVS:
                    keep_args = False
                    strip_n = None
                else:
                    strip_n = 0
            elif name in STRIP_ALL:
                keep_args = False
            elif name in STRIP_FIRST:
                strip_n = STRIP_FIRST[name]
            out.append(" " * (j - i))
            i = j
            stripped = 0
            while True:
                k = _skip_ws(text, i)
                if k < len(text) and text[k] == "[":
                    e = _group_end(text, k, "[", "]")
                    out.append(re.sub(r"[^\n]", " ", text[i:e]))
                    i = e
                    continue
                if k < len(text) and text[k] == "{" and (not keep_args or (strip_n and stripped < strip_n)):
                    e = _group_end(text, k, "{", "}")
                    out.append(re.sub(r"[^\n]", " ", text[i:e]))
                    i = e
                    stripped += 1
                    continue
                break
            continue
        if text[i] == "\\" and i + 1 < len(text):
            out.append(" " if text[i + 1] != "\n" else "\n")
            out.append(" " if text[i + 1] != "\n" else "")
            i += 2
            continue
        ch = text[i]
        out.append(" " if ch in "{}&~" else ch)
        i += 1
    return "".join(out)


def _denylist() -> list[str]:
    path = os.environ.get("SGW_DENYLIST")
    if not path or not Path(path).exists():
        return []
    return [
        t.strip()
        for t in Path(path).read_text(encoding="utf-8").splitlines()
        if t.strip() and not t.startswith("#")
    ]


def lint_text(source: str, path: str, lexicon_mode: str = "advisory") -> list[Finding]:
    rules, allow, lexicon = load_config()
    prose = strip_latex(source)
    lex_severity = "error" if lexicon_mode == "enforced" else "advice"
    deny = _denylist()
    findings: list[Finding] = []
    for lineno, line in enumerate(prose.splitlines(), start=1):
        if not line.strip():
            continue
        for r in rules:
            for m in r["regex"].finditer(line):
                findings.append(
                    Finding(path, lineno, r["id"], r["severity"], m.group(0).strip(), r["message"])
                )
        digits_line = line
        for a in allow:
            digits_line = a.sub(" ", digits_line)
        for m in re.finditer(r"[\d][\d.,]*", digits_line):
            findings.append(
                Finding(
                    path,
                    lineno,
                    "bare-digit",
                    "error",
                    m.group(0),
                    "numbers only as macros from numbers.yaml (\\sgwnum{key})",
                )
            )
        for t in lexicon:
            for m in t["regex"].finditer(line):
                findings.append(
                    Finding(
                        path, lineno, "lexicon", lex_severity, m.group(0), f"plain language: {t['plain']}"
                    )
                )
        for term in deny:
            if term.lower() in line.lower():
                findings.append(
                    Finding(
                        path,
                        lineno,
                        "denylist",
                        "error",
                        "<private term>",
                        "a private name from SGW_DENYLIST appears",
                    )
                )
    return findings


def lint_files(paths: list[Path], lexicon_mode: str = "advisory") -> list[Finding]:
    findings: list[Finding] = []
    for p in paths:
        try:
            shown = str(p.relative_to(Path.cwd()))
        except ValueError:
            shown = str(p)
        findings += lint_text(p.read_text(encoding="utf-8"), shown, lexicon_mode)
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--lexicon", choices=["enforced", "advisory"], default="advisory")
    args = parser.parse_args(argv)
    findings = lint_files(args.files, args.lexicon)
    for f in findings:
        print(f)
    errors = sum(f.severity == "error" for f in findings)
    print(f"{errors} errors, {len(findings) - errors} advisories")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

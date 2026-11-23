import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("prose_lint", HERE / "prose_lint.py")
prose_lint = importlib.util.module_from_spec(spec)
sys.modules["prose_lint"] = prose_lint
spec.loader.exec_module(prose_lint)


def rules_hit(body: str, mode: str = "advisory") -> list[tuple[str, str]]:
    source = "\\documentclass{article}\n\\begin{document}\n" + body + "\n\\end{document}\n"
    return [(f.rule, f.severity) for f in prose_lint.lint_text(source, "t.tex", mode)]


@pytest.mark.parametrize(
    "body,rule",
    [
        ("We propose a platform.", "first-person-plural"),
        ("The platform is seamless.", "hype-word"),
        ("The clock moves --- fast.", "em-dash"),
        ("One clause; another clause.", "semicolon"),
        ("Company A prepared this.", "consultancy-name"),
        ("SGW is a fictional utility.", "invented-client"),
        ("Open the Picture module.", "module-name"),
        ("The pilot costs 35 million.", "bare-digit"),
        ("Owner is TBD.", "requirement-filler"),
        ("See DC-45 for details.", "planning-id"),
    ],
)
def test_rule_fires(body, rule):
    assert (rule, "error") in rules_hit(body)


@pytest.mark.parametrize(
    "body",
    [
        "The platform serves \\sgwnum{footprint.residents} residents.",
        "PS-17 feeds the hospital zone. FR-01 and D1 to D5 are in scope.",
        "Phase 1 starts after gate 2, see Table~\\ref{tab:x} and \\cite{nist2023airmf}.",
        "Hurricane Helene in 2024 is the baseline storm.",
        "\\begin{tabularx}{\\textwidth}{L{1.2cm} Y} A & B \\\\ \\end{tabularx}",
        "\\begin{tikzpicture}\\node at (0,1) {12 h};\\end{tikzpicture}",
        "\\resizebox{0.9\\textwidth}{!}{\\input{diagrams/container}}",
        "\\sgwsection{problem}{1.25}{Storms cost SGW most where power and water decisions meet}",
        "Accessibility follows WCAG 2.2 AA. Risk follows the NIST AI RMF 1.0.",
        "The consultancy A prepared this for SGW.",
    ],
)
def test_clean_prose_passes(body):
    assert [r for r in rules_hit(body) if r[1] == "error"] == []


def test_lexicon_is_enforced_only_for_briefing():
    body = "The LLM explains each T3 sign-off."
    assert ("lexicon", "error") in rules_hit(body, "enforced")
    assert ("lexicon", "error") not in rules_hit(body, "advisory")
    assert ("lexicon", "advice") in rules_hit(body, "advisory")


def test_comments_and_preamble_are_ignored():
    source = "\\documentclass[11pt]{scrartcl}\n\\begin{document}\nText. % we 12; seamless\n\\end{document}\n"
    assert prose_lint.lint_text(source, "t.tex") == []


def test_line_numbers_are_preserved():
    source = "\\documentclass{article}\n\\begin{document}\n\nGood line.\nWe fail here.\n\\end{document}\n"
    findings = prose_lint.lint_text(source, "t.tex")
    assert [f.line for f in findings if f.rule == "first-person-plural"] == [5]


def test_denylist(tmp_path, monkeypatch):
    deny = tmp_path / "deny.txt"
    deny.write_text("Secretcorp\n", encoding="utf-8")
    monkeypatch.setenv("SGW_DENYLIST", str(deny))
    assert ("denylist", "error") in rules_hit("Built at Secretcorp labs.")

"""Build the SGW documents: numbers -> palette -> figures -> pdflatex, bibtex, pdflatex x2 -> lint -> budgets.

    uv run python docs/build.py all           # palette, numbers, figures, diagrams, prd, briefing
    uv run python docs/build.py prd           # one document (also: briefing)
    uv run python docs/build.py diagrams      # each TikZ diagram as its own PDF and a 60 dpi PNG preview
    uv run python docs/build.py lint          # prose lint and palette drift check, no TeX run
    uv run python docs/build.py all --final   # refuse stub numbers, unknown keys and pending boxes

Outputs: docs/pdf/<doc>.pdf and docs/pdf/diagrams/. Intermediate files: var/docs/ (git-ignored).
Toolchain: pdflatex, bibtex, pdfinfo, pdftoppm (TeX Live and poppler). No latexmk, no biber.
TeX runs take the machine-wide heavy lock (<main checkout>/.locks/heavy); --no-lock skips it.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

DOCS = Path(__file__).resolve().parent
REPO = DOCS.parent
LATEX = DOCS / "latex"
SHARED = LATEX / "shared"
DIAGRAMS = SHARED / "diagrams"
FIGURES_SRC = DOCS / "figures"
FIGURES_OUT = SHARED / "figures"
FIGURE_SCRIPTS = ("fig_*.py", "prd_*.py", "brief_*.py")
PDF_OUT = DOCS / "pdf"
WORK = REPO / "var" / "docs"


@dataclass(frozen=True)
class Budget:
    """Page budget between two \\sgwmark labels (inclusive), or the whole PDF when marks are None."""

    name: str
    start: str | None
    end: str | None
    max_pages: int
    exact_start_page: int | None = None


@dataclass(frozen=True)
class Doc:
    name: str
    main: str
    budgets: tuple[Budget, ...]
    lexicon: str  # "enforced" or "advisory"
    extra_lint: tuple[str, ...] = field(default_factory=tuple)


DOCUMENTS: dict[str, Doc] = {
    "prd": Doc(
        "prd",
        "prd/prd.tex",
        (
            Budget("summary is page one", "bodystart", "summaryend", 1, exact_start_page=1),
            Budget("body (s1-s12)", "bodystart", "bodyend", 12, exact_start_page=1),
            Budget("references", "appendixstart", "appendixend", 2),
            Budget("whole document", None, None, 13),
        ),
        lexicon="advisory",
    ),
    "briefing": Doc(
        "briefing",
        "briefing/briefing.tex",
        (
            Budget("page one stands alone", "bodystart", "page1end", 1, exact_start_page=1),
            Budget("body", "bodystart", "bodyend", 3),
            Budget("appendix", "appendixstart", "appendixend", 1),
            Budget("whole memo", None, None, 4),
        ),
        lexicon="enforced",
    ),
}


def log(msg: str) -> None:
    print(f"[docs] {msg}", flush=True)


def run(
    cmd: list[str], cwd: Path, env: dict[str, str] | None = None, check: bool = True
) -> subprocess.CompletedProcess:
    proc = subprocess.run(  # noqa: S603
        cmd, cwd=cwd, env=env, capture_output=True, text=True, errors="replace", check=False
    )
    if check and proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-40:])
        raise SystemExit(f"[docs] FAILED ({proc.returncode}): {' '.join(cmd)}\n{tail}")
    return proc


def need(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise SystemExit(f"[docs] missing tool: {tool} (install TeX Live and poppler)")
    return path


def lock_dir() -> Path:
    try:
        common = Path(run(["git", "rev-parse", "--git-common-dir"], REPO).stdout.strip())
        root = (REPO / common).resolve().parent if not common.is_absolute() else common.parent
    except (SystemExit, FileNotFoundError):
        root = REPO
    return root / ".locks" / "heavy"


@contextlib.contextmanager
def heavy_lock(enabled: bool, timeout_s: int = 1800):
    if not enabled:
        yield
        return
    path = lock_dir()
    path.parent.mkdir(parents=True, exist_ok=True)
    waited = 0
    while True:
        try:
            path.mkdir()
            break
        except FileExistsError:
            if waited >= timeout_s:
                raise SystemExit(f"[docs] heavy lock {path} held for {timeout_s} s; giving up") from None
            if waited % 60 == 0:
                log(f"waiting for heavy lock {path}")
            time.sleep(10)
            waited += 10
    log(f"heavy lock taken: {path}")
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            path.rmdir()
        log("heavy lock released")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def step_palette() -> None:
    style = load_module("sgw_docs_style", FIGURES_SRC / "style.py")
    style.write_palette_tex()
    log(f"palette from DESIGN.md -> {style.PALETTE_TEX.relative_to(REPO)}")


def step_numbers() -> None:
    yaml_path = REPO / "data" / "numbers" / "numbers.yaml"
    generator = REPO / "src" / "sgw" / "common" / "numbers.py"
    if yaml_path.exists() and generator.exists():
        run(
            [sys.executable, "-m", "sgw.common.numbers", "--tex"],
            REPO,
            env={**os.environ, "PYTHONPATH": str(REPO / "src")},
        )
        log("numbers.tex generated from data/numbers/numbers.yaml")
    else:
        log("numbers.yaml or its generator not present yet: documents use numbers-stub.tex (marked 'stub')")


def step_figures() -> None:
    scripts = sorted(p for pattern in FIGURE_SCRIPTS for p in FIGURES_SRC.glob(pattern))
    for script in scripts:
        module = load_module(f"sgw_fig_{script.stem}", script)
        outputs = module.build(FIGURES_OUT)
        log(f"figure {script.stem}: {', '.join(p.name for p in outputs)}")


def tex_env() -> dict[str, str]:
    sep = os.pathsep
    env = dict(os.environ)
    env["TEXINPUTS"] = sep.join([".", str(SHARED), str(SHARED / "diagrams"), str(FIGURES_OUT), ""])
    env["BIBINPUTS"] = sep.join([".", str(SHARED), str(LATEX / "prd"), ""])
    env["max_print_line"] = "1000"
    return env


def pdflatex(src_dir: Path, main: str, out_dir: Path, preamble: str) -> None:
    jobname = Path(main).stem
    run(
        [
            need("pdflatex"),
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            f"-output-directory={out_dir}",
            f"-jobname={jobname}",
            f"{preamble}\\input{{{main}}}",
        ],
        src_dir,
        env=tex_env(),
    )


def compile_tex(src_dir: Path, main: str, out_dir: Path, final: bool) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    jobname = Path(main).stem
    mode = "final" if final else "draft"
    preamble = f"\\def\\sgwbuildmode{{{mode}}}"
    pdflatex(src_dir, main, out_dir, preamble)
    aux = (out_dir / f"{jobname}.aux").read_text(encoding="utf-8", errors="replace")
    if "\\citation" in aux and "\\bibdata" in aux:
        run([need("bibtex"), jobname], out_dir, env=tex_env())
    pdflatex(src_dir, main, out_dir, preamble)
    pdflatex(src_dir, main, out_dir, preamble)
    report_log(out_dir / f"{jobname}.log")
    return out_dir / f"{jobname}.pdf"


def report_log(log_path: Path) -> None:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    font = re.search(r"SGW-FONT: (.+)", text)
    numbers = re.search(r"SGW-NUMBERS: (.+)", text)
    warnings = re.findall(r"^(?:LaTeX|Package \w+) Warning: .*$", text, re.M)
    overfull = len(re.findall(r"^Overfull \\hbox", text, re.M))
    log(
        f"  font: {font.group(1) if font else 'unknown'}; "
        f"numbers: {numbers.group(1) if numbers else 'unknown'}"
    )
    log(f"  warnings: {len(warnings)}; overfull hboxes: {overfull}")
    for w in warnings[:8]:
        log(f"    {w[:160]}")


def pdf_pages(pdf: Path) -> int:
    out = run([need("pdfinfo"), str(pdf)], pdf.parent).stdout
    return int(re.search(r"^Pages:\s+(\d+)", out, re.M).group(1))


def aux_marks(aux: Path) -> tuple[dict[str, int], dict[str, float]]:
    text = aux.read_text(encoding="utf-8", errors="replace")
    marks = {
        m.group(1): int(m.group(2))
        for m in re.finditer(r"\\newlabel\{sgw:mark:([\w-]+)\}\{\{[^{}]*\}\{(\d+)\}", text)
    }
    sections = {
        m.group(1): int(m.group(3))
        for m in re.finditer(r"\\newlabel\{sgw:sec:([\w-]+)\}\{\{([^{}]*)\}\{(\d+)\}", text)
    }
    numbers = {
        m.group(1): m.group(2) for m in re.finditer(r"\\newlabel\{sgw:sec:([\w-]+)\}\{\{([^{}]*)\}", text)
    }
    budgets = {
        m.group(1): float(m.group(2)) for m in re.finditer(r"\\sgwbudget\{([\w-]+)\}\{([\d.]+)\}", text)
    }
    order = sorted(sections, key=lambda k: (sections[k], int(numbers[k]) if numbers[k].isdigit() else 0))
    section_budgets = {k: budgets[k] for k in order if k in budgets}
    marks.update({f"sec:{k}": v for k, v in sections.items()})
    return marks, section_budgets


def check_budgets(doc: Doc, pdf: Path, aux: Path) -> list[str]:
    total = pdf_pages(pdf)
    marks, section_budgets = aux_marks(aux)
    errors = []
    log(f"  pages (pdfinfo): {total}")
    for b in doc.budgets:
        if b.start is None:
            used, start = total, 1
        else:
            if b.start not in marks or b.end not in marks:
                errors.append(f"{doc.name}: budget '{b.name}': marks {b.start}/{b.end} missing")
                continue
            start, used = marks[b.start], marks[b.end] - marks[b.start] + 1
        ok = used <= b.max_pages and (b.exact_start_page is None or start == b.exact_start_page)
        where = (
            "" if b.exact_start_page is None else f", starts on page {start} (must be {b.exact_start_page})"
        )
        log(f"  budget {b.name}: {used} of {b.max_pages} pages{where} -> {'ok' if ok else 'OVER'}")
        if not ok:
            errors.append(f"{doc.name}: budget '{b.name}' broken: {used} pages > {b.max_pages}{where}")
    if section_budgets:
        spans = ", ".join(f"{k} from p{marks[f'sec:{k}']} (budget {b:g})" for k, b in section_budgets.items())
        log(f"  sections: {spans}")
    return errors


def lint(doc_names: list[str]) -> list[str]:
    linter = load_module("sgw_prose_lint", LATEX / "lint" / "prose_lint.py")
    errors: list[str] = []
    for name in doc_names:
        doc = DOCUMENTS[name]
        paths = [LATEX / doc.main, *(LATEX / p for p in doc.extra_lint)]
        findings = linter.lint_files(paths, lexicon_mode=doc.lexicon)
        for f in findings:
            print(f"  {f}")
        errs = [f for f in findings if f.severity == "error"]
        log(
            f"lint {name}: {len(errs)} errors, {len(findings) - len(errs)} advisories (lexicon {doc.lexicon})"
        )
        errors += [str(f) for f in errs]
    style = load_module("sgw_docs_style", FIGURES_SRC / "style.py")
    if not style.palette_in_sync():
        errors.append("docs/latex/shared/sgwpalette.tex is out of sync with DESIGN.md (run build.py palette)")
    return errors


def build_doc(name: str, final: bool) -> list[str]:
    doc = DOCUMENTS[name]
    src = LATEX / doc.main
    out_dir = WORK / name
    log(f"build {name} ({'final' if final else 'draft'})")
    pdf = compile_tex(src.parent, src.name, out_dir, final)
    PDF_OUT.mkdir(parents=True, exist_ok=True)
    target = PDF_OUT / f"{name}.pdf"
    shutil.copyfile(pdf, target)
    log(f"  -> {target.relative_to(REPO)}")
    return check_budgets(doc, target, out_dir / f"{Path(doc.main).stem}.aux")


DIAGRAM_WRAPPER = r"""\documentclass[border=4pt]{standalone}
\usepackage{sgwfonts}
\usepackage{sgwdiagrams}
\usepackage{sgwnumbers}
\begin{document}
\input{%s}
\end{document}
"""


def build_diagrams(final: bool) -> list[Path]:
    out_dir = WORK / "diagrams"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir = PDF_OUT / "diagrams"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    built = []
    for src in sorted(DIAGRAMS.glob("*.tex")):
        wrapper = out_dir / f"{src.stem}-standalone.tex"
        wrapper.write_text(DIAGRAM_WRAPPER % src.stem, encoding="utf-8", newline="\n")
        mode = "final" if final else "draft"
        pdflatex(out_dir, wrapper.name, out_dir, f"\\def\\sgwbuildmode{{{mode}}}")
        target = pdf_dir / f"{src.stem}.pdf"
        shutil.copyfile(out_dir / f"{src.stem}-standalone.pdf", target)
        run(
            [
                need("pdftoppm"),
                "-r",
                "60",
                "-png",
                "-singlefile",
                str(target),
                str(out_dir / f"{src.stem}-60dpi"),
            ],
            out_dir,
        )
        log(
            f"diagram {src.stem} -> {target.relative_to(REPO)} "
            f"(preview var/docs/diagrams/{src.stem}-60dpi.png)"
        )
        built.append(target)
    return built


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "target",
        choices=[
            "all",
            "docs",
            "prd",
            "briefing",
            "diagrams",
            "figures",
            "palette",
            "numbers",
            "lint",
        ],
    )
    parser.add_argument(
        "--final", action="store_true", help="refuse stub numbers, unknown keys and pending content"
    )
    parser.add_argument("--no-lock", action="store_true", help="skip the machine-wide heavy lock")
    args = parser.parse_args(argv)

    docs = {"all": list(DOCUMENTS), "docs": list(DOCUMENTS)}.get(
        args.target, [args.target] if args.target in DOCUMENTS else []
    )
    errors: list[str] = []
    if args.target == "palette":
        step_palette()
        return 0
    if args.target == "numbers":
        step_numbers()
        return 0
    if args.target == "lint":
        errors = lint(list(DOCUMENTS))
    else:
        step_palette()
        step_numbers()
        if args.target in ("all", "docs", "figures", *DOCUMENTS):
            step_figures()
        if args.target != "figures":
            with heavy_lock(not args.no_lock):
                if args.target in ("all", "diagrams"):
                    build_diagrams(args.final)
                for name in docs:
                    errors += build_doc(name, args.final)
        if docs:
            errors += lint(docs)
    if errors:
        log(f"{len(errors)} problem(s):")
        for e in errors:
            log(f"  - {e}")
        return 1
    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

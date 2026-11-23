# Deliverables

The two written deliverables of the assessment, as final PDFs. Both are built from LaTeX sources in this repository and read every number from the numbers registry (`data/numbers/numbers.yaml`).

| Document | For whom | What it is for | LaTeX source |
| --- | --- | --- | --- |
| [prd.pdf](prd.pdf) | The technical delivery team (engineers, architects, data people) | Product requirements, 12 pages. Summary with the decisions asked of SGW, problem and context, assumptions and unknowns, users, requirements with prototype status, AI capabilities, architecture and integrations, data, security and human oversight, metrics, MVP scope and delivery plan, risks, references. Sections follow the areas of the task brief in order. | [`docs/latex/prd/prd.tex`](../latex/prd/prd.tex) |
| [executive-briefing.pdf](executive-briefing.pdf) | SGW senior leadership | Executive briefing, 3 pages and a page of references. Decision asked, business value, cost and return, delivery plan with gates, governance and compliance, scalability. Page one stands alone. | [`docs/latex/briefing/briefing.tex`](../latex/briefing/briefing.tex) |

Shared parts (styles, diagrams, generated numbers) are in [`docs/latex/shared/`](../latex/shared/).

## Rebuild

The build needs TeX Live (`pdflatex`, `bibtex`, the `charter` and `fira` font packages) and poppler (`pdfinfo`, `pdftoppm`). It checks the page budgets and runs the prose lint.

```sh
uv run python -m sgw.common.numbers --check --audit
uv run python scripts/build_docs.py prd --final
uv run python scripts/build_docs.py briefing --final
```

The PDFs are written to `docs/pdf/` (not tracked). Copy them here after a rebuild:

```sh
cp docs/pdf/prd.pdf docs/deliverables/prd.pdf
cp docs/pdf/briefing.pdf docs/deliverables/executive-briefing.pdf
```

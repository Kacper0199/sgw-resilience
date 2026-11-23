#!/usr/bin/env bash
# Build every docs/diagrams/src/<name>.tex (a bare tikzpicture in the sgw style) into
# docs/images/diagrams/<name>.png (1760 px wide, shown at 880 px on GitHub) and <name>.svg.
# Usage: docs/diagrams/build.sh [name ...]   (no names: all diagrams)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
shared="$repo/docs/latex/shared"
out="$repo/docs/images/diagrams"
work="$repo/var/docs/md-diagrams"
mkdir -p "$out" "$work"
names=("$@")
if [ ${#names[@]} -eq 0 ]; then
  for f in "$here"/src/*.tex; do names+=("$(basename "$f" .tex)"); done
fi
for name in "${names[@]}"; do
  src="$here/src/$name.tex"
  [ -f "$src" ] || { echo "missing $src" >&2; exit 1; }
  cat > "$work/$name-wrap.tex" <<TEX
\\documentclass[border=6pt]{standalone}
\\usepackage{sgwfonts}
\\usepackage{sgwnumbers}
\\usepackage{sgwdiagrams}
\\begin{document}
\\input{$src}
\\end{document}
TEX
  (cd "$work" && TEXINPUTS=".:$shared:$shared/diagrams:$here/src:" pdflatex -interaction=nonstopmode -halt-on-error "$name-wrap.tex" >/dev/null) \
    || { echo "LaTeX failed for $name, see $work/$name-wrap.log" >&2; exit 1; }
  pdftocairo -png -singlefile -scale-to-x 1760 -scale-to-y -1 "$work/$name-wrap.pdf" "$out/$name"
  pdftocairo -svg "$work/$name-wrap.pdf" "$out/$name.svg"
  echo "diagram $name -> docs/images/diagrams/$name.png, .svg"
done

#!/usr/bin/env bash
# Batch gate for review/REVIEW-PLAN.md rule R6.
# Builds the manuscript in a scratch directory (the working tree is never
# written to), then reports pages, undefined refs/citations, rerun warnings,
# overfull boxes and bibtex warnings. Exit 0 = gate passed.
#
#   bash review/tools/build_gate.sh [--keep-pdf PATH]
set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
keep_pdf=""
if [[ "${1:-}" == "--keep-pdf" ]]; then keep_pdf="${2:?--keep-pdf needs a path}"; fi

work="$(mktemp -d /tmp/fd-build-XXXXXX)"
trap 'rm -rf "$work"' EXIT
export TEXINPUTS="$repo_root:" BIBINPUTS="$repo_root:" BSTINPUTS="$repo_root:"

run_tex() {
  (cd "$repo_root" && pdflatex -interaction=nonstopmode -halt-on-error \
    -output-directory="$work" main.tex >"$work/$1.out" 2>&1)
}

fail=0
run_tex pass1 || { echo "FAIL: pdflatex pass 1 (see below)"; tail -20 "$work/pass1.out"; exit 1; }
(cd "$work" && bibtex main >"$work/bibtex.out" 2>&1) || { echo "FAIL: bibtex"; cat "$work/bibtex.out"; exit 1; }
for i in 2 3 4; do run_tex "pass$i" || { echo "FAIL: pdflatex pass $i"; tail -20 "$work/pass$i.out"; exit 1; }; done

log="$work/main.log"
pages=$(grep -o 'Output written on .* (\([0-9]*\) pages' "$work/pass4.out" | grep -o '([0-9]*' | tr -d '(')
undef=$(grep -Ec "(Citation|Reference) .* undefined" "$log")
rerun=$(grep -c "Rerun to get" "$log")
bibw=$(grep -c "^Warning--" "$work/bibtex.out")

echo "pages:                 $pages"
echo "undefined refs/cites:  $undef"
echo "rerun warnings:        $rerun"
echo "bibtex warnings:       $bibw"
grep "^Warning--" "$work/bibtex.out" | sed 's/^/    /'
echo "overfull hboxes (file: lines, width; file = last .tex opened, approximate after an \\input closes):"
# Attribute each overfull box to the .tex file most recently opened in the log.
python3 - "$log" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="latin-1").read().replace("\n", "")
cur = "main.tex"
for m in re.finditer(r"\(([^()\s]*?([^/()\s]+\.tex))|Overfull \\hbox \(([0-9.]+)pt too wide\) in (?:paragraph|alignment) at lines (\d+)--(\d+)", text):
    if m.group(2):
        cur = m.group(2)
    elif m.group(3):
        print(f"    {cur}: lines {m.group(4)}-{m.group(5)}, {float(m.group(3)):.1f} pt")
PY
cp "$log" /tmp/oce-work/last-build.log 2>/dev/null || true
big=$(grep -Eo 'Overfull \\hbox \(([0-9.]+)pt' "$log" | grep -Eo '[0-9.]+' | awk '$1>10' | wc -l)
echo "overfull > 10pt:       $big"

[[ "$undef" -eq 0 ]] || { echo "GATE: undefined references/citations"; fail=1; }
[[ "$rerun" -eq 0 ]] || { echo "GATE: cross-references not settled"; fail=1; }

if [[ -n "$keep_pdf" ]]; then cp "$work/main.pdf" "$keep_pdf"; echo "pdf kept at:           $keep_pdf"; fi
[[ $fail -eq 0 ]] && echo "GATE: PASS" || echo "GATE: FAIL"
exit $fail

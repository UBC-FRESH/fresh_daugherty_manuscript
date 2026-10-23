#!/usr/bin/env bash
# End-to-end check of review/bin/review_import.py against the synthetic fixture
# exports. Not part of the review workflow; run it when you change the helper.
#
#   review/tools/venv-python review/tools/check_import.sh
#
# It proves the import works on real exporter output and that your notes survive
# a refresh. It proves nothing about Overleaf authentication or endpoints.

set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
real_root="$(cd "$here/../.." && pwd)"
venv="$here/.venv"
work="${OCE_CHECK_DIR:-}"
py="$venv/bin/python"

# Everything below runs in a throwaway copy of the repository. An earlier
# version ran against the real tree and its cleanup deleted a real import
# (review/imports, review/current) on 2026-10-04. Never point this at real data.
if [[ -z "$work" ]]; then
  work="$(mktemp -d "${TMPDIR:-/tmp}/oce-check-XXXXXX")"
  trap 'rm -rf "$work"' EXIT
fi
repo_root="$work/repo"
mkdir -p "$repo_root"
tar -C "$real_root" \
  --exclude='review/imports' --exclude='review/current' --exclude='review/imports-staging' \
  --exclude='review/tools/.venv' --exclude='review/tools/oce-out' --exclude='review/config/session-cookie' \
  -cf - review main.tex references.bib sections | tar -C "$repo_root" -xf -
git -C "$repo_root" init -q
git -C "$repo_root" -c user.name=check -c user.email=check@localhost add -A
git -C "$repo_root" -c user.name=check -c user.email=check@localhost commit -q -m sandbox
[[ "$repo_root" != "$real_root" ]] || { echo "refusing to run against the real repository" >&2; exit 2; }

fail=0
check() {  # check <description> <expectation> <actual>
  if [[ "$2" == "$3" ]]; then
    printf '  ok    %s\n' "$1"
  else
    printf '  FAIL  %s\n        expected: %s\n        actual:   %s\n' "$1" "$2" "$3"
    fail=1
  fi
}
contains() {  # contains <description> <needle> <file>
  if grep -qF -- "$2" "$3"; then printf '  ok    %s\n' "$1"
  else printf '  FAIL  %s (missing %q)\n' "$1" "$2"; fail=1; fi
}
absent() {
  if grep -qF -- "$2" "$3"; then printf '  FAIL  %s (found %q)\n' "$1" "$2"; fail=1
  else printf '  ok    %s\n' "$1"; fi
}

fixture_cfg="$work/config.txt"
cp "$repo_root/review/notes/TRIAGE.md" "$work/TRIAGE.pristine"

printf '\n== 1. build fixture exports ==\n'
mkdir -p "$work"
"$py" "$here/make_fixture_export.py" --out "$work/round-1" --paper "$work/paper" --round 1 >/dev/null
"$py" "$here/make_fixture_export.py" --out "$work/round-2" --paper "$work/paper" --round 2 >/dev/null
printf '  ok    round-1 and round-2 fixture exports written to %s\n' "$work"
printf 'https://www.overleaf.com/project/abcdef0123456789abcdef01\n' > "$fixture_cfg"

printf '\n== 2. dry run writes nothing ==\n'
cp "$repo_root/review/notes/TRIAGE.md" "$work/TRIAGE.before"
python3 "$repo_root/review/bin/review_import.py" "$work/round-1" --config "$fixture_cfg" --dry-run >/dev/null 2>&1
check "review/imports still absent after --dry-run" "absent" \
  "$([[ -e "$repo_root/review/imports" ]] && echo present || echo absent)"
check "TRIAGE.md untouched by --dry-run" "same" \
  "$(cmp -s "$repo_root/review/notes/TRIAGE.md" "$work/TRIAGE.before" && echo same || echo changed)"

printf '\n== 3. first import ==\n'
python3 "$repo_root/review/bin/review_import.py" "$work/round-1" --config "$fixture_cfg" --label round-1 >/dev/null 2>&1
cur="$repo_root/review/current"
check "comments.md exists" "yes" "$([[ -f "$cur/comments.md" ]] && echo yes || echo no)"
check "INDEX.md exists" "yes" "$([[ -f "$cur/INDEX.md" ]] && echo yes || echo no)"
check "PROVENANCE.md exists" "yes" "$([[ -f "$cur/PROVENANCE.md" ]] && echo yes || echo no)"
check "threads.json parses" "ok" "$(python3 -c "import json;json.load(open('$cur/threads.json'));print('ok')" 2>/dev/null || echo bad)"
check "markdown kept verbatim" "yes" \
  "$(cmp -s "$cur/comments.md" "$(ls "$repo_root"/review/imports/*/comments*.md | head -1)" && echo yes || echo no)"
check "resolved thread survives the import" "1" \
  "$(python3 -c "import json;print(sum(1 for t in json.load(open('$cur/threads.json'))['threads'].values() if t['resolved']))")"
check "replies survive" "3" \
  "$(python3 -c "import json;print(sum(t['reply_count'] for t in json.load(open('$cur/threads.json'))['threads'].values()))")"
check "orphan thread kept, flagged" "1" \
  "$(python3 -c "import json;print(sum(1 for t in json.load(open('$cur/threads.json'))['threads'].values() if not t['anchored_to_live_source']))")"
contains "stale anchor reported in provenance" "Stale anchors" "$cur/PROVENANCE.md"
contains "renamed section file detected" "3_methods.tex" "$cur/PROVENANCE.md"
contains "overleaf revision recorded as unknown" "Overleaf-side revision:" "$cur/PROVENANCE.md"
contains "project id verified against config" "matches the export" "$cur/PROVENANCE.md"

printf '\n== 4. user writes notes in the generated table ==\n'
python3 - "$repo_root/review/notes/TRIAGE.md" <<'PY'
import sys
from pathlib import Path
notes = {
    "65a1f0a1b2c3d4e5f60718": "edit: tighten this sentence",
    "65a1f0a1b2c3d4e5f60719": "todo: state the cell count",
}
out = []
for line in Path(sys.argv[1]).read_text().splitlines():
    if line.startswith("| `65a"):
        cells = line.strip().strip("|").split("|")
        tid = cells[0].strip().strip("`")
        assert tid, f"could not read the thread id out of {line!r}"
        cells[-1] = f" {notes.get(tid, '')} "
        line = "| " + " | ".join(c.strip() for c in cells) + " |"
    out.append(line)
Path(sys.argv[1]).write_text("\n".join(out) + "\n")
print("  ok    notes injected into the generated table")
PY
contains "note written" "todo: state the cell count" "$repo_root/review/notes/TRIAGE.md"

printf '\n== 5. second import: notes survive, changes detected ==\n'
python3 "$repo_root/review/bin/review_import.py" "$work/round-2" --config "$fixture_cfg" --label round-2 >/dev/null 2>&1
contains "old note survived the refresh" "todo: state the cell count" "$repo_root/review/notes/TRIAGE.md"
contains "second note survived" "edit: tighten this sentence" "$repo_root/review/notes/TRIAGE.md"
contains "hand-written text above the block survived" "Do not paste long verbatim passages" "$repo_root/review/notes/TRIAGE.md"
contains "new thread reported" "New threads (1)" "$cur/CHANGES.md"
contains "resolution reported" "Marked resolved since the last import" "$cur/CHANGES.md"
contains "new reply reported" "Threads with new replies" "$cur/CHANGES.md"
contains "edited comment reported" "Comments edited after you last saw them" "$cur/CHANGES.md"
contains "new tracked change reported" "New tracked changes" "$cur/CHANGES.md"
check "no separator row parsed as a note" "0" \
  "$(grep -c '^| `---`' "$repo_root/review/notes/TRIAGE.md" || true)"

printf '\n== 6. project mismatch is reported, not swallowed ==\n'
# The real config names the real project; the fixture export names the fixture
# one. That has to be reported rather than quietly accepted.
python3 "$repo_root/review/bin/review_import.py" "$work/round-2" \
  --compare-to none --dry-run > "$work/mismatch.txt" 2>&1 || true
contains "mismatch surfaced" "Project mismatch" "$work/mismatch.txt"

printf '\n== 7. browser-extension shape: an export with no source/ ==\n'
# The extension writes comments-<date>.md and comments.json but no source/
# snapshot. That is the recommended route, so it has to work and it has to say
# plainly that anchors could not be checked against the exported text.
"$py" "$here/make_fixture_export.py" --out "$work/extension" --paper "$work/paper" --round 2 --no-source >/dev/null
python3 "$repo_root/review/bin/review_import.py" "$work/extension" \
  --config "$fixture_cfg" --label ext >/dev/null 2>&1
check "import of an extension-shaped export works" "yes" "$([[ -f "$cur/comments.md" ]] && echo yes || echo no)"
contains "missing source snapshot is reported" "snapshot in this export" "$cur/PROVENANCE.md"
contains "comparison is recorded as UNKNOWN" "**UNKNOWN.**" "$cur/PROVENANCE.md"
contains "worktree anchor check still ran" "Against the working tree" "$cur/PROVENANCE.md"
contains "changes against the previous import still work" "What changed since the previous import" "$cur/CHANGES.md"
check "threads still counted" "7" \
  "$(python3 -c "import json;print(len(json.load(open('$cur/threads.json'))['threads']))")"

printf '\n== 8. leaving the repository untouched ==\n'
check "no manuscript file modified" "clean" \
  "$(git -C "$repo_root" status --porcelain -- '*.tex' '*.bib' 'figures' | wc -l | tr -d ' ' | sed 's/^0$/clean/;s/^[1-9].*/dirty/')"
check "review/imports is gitignored" "ignored" \
  "$(git -C "$repo_root" check-ignore -q review/imports && echo ignored || echo tracked)"
check "review/current is gitignored" "ignored" \
  "$(git -C "$repo_root" check-ignore -q review/current && echo ignored || echo tracked)"
check "the session cookie path is gitignored" "ignored" \
  "$(git -C "$repo_root" check-ignore -q review/config/session-cookie && echo ignored || echo tracked)"

printf '\n== 9. clean up ==\n'
rm -rf "$repo_root/review/imports" "$repo_root/review/current"
cp "$work/TRIAGE.pristine" "$repo_root/review/notes/TRIAGE.md"
printf '  ok    test artifacts removed; TRIAGE.md back to its scaffold\n'

if [[ "$fail" -ne 0 ]]; then printf '\nFAILURES\n'; exit 1; fi
printf '\nAll checks passed.\n'
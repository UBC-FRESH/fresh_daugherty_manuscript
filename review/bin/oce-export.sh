#!/usr/bin/env bash
# Export Overleaf comments from inside the container, using the pinned exporter
# in an isolated venv. Optional: the browser-extension route (see review/README.md)
# needs no Overleaf credentials on this box at all.
#
# Secrets: the session cookie is never passed on the command line (--cookie shows
# up in shell history and in ps for every other process on the machine). It is
# read from $OVERLEAF_SESSION, else from review/config/session-cookie (gitignored,
# mode 600), else from a no-echo prompt. In every case it goes to the exporter
# through the environment variable it reads itself.
#
#   ./review/bin/oce-export.sh --doctor        # check connectivity and cookies
#   ./review/bin/oce-export.sh                 # export into review/tools/oce-out
#   ./review/bin/oce-export.sh --include-resolved-only   # see --help for the rest
#
# This script never pushes, never commits and never touches the manuscript. It
# writes only into review/tools/oce-out/, which review_import.py then ingests.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
review_root="$(cd "$here/.." && pwd)"
repo_root="$(cd "$review_root/.." && pwd)"
config_dir="$review_root/config"
venv="$review_root/tools/.venv"
out_dir="$review_root/tools/oce-out"
session_file="$config_dir/session-cookie"
project_file="$config_dir/overleaf-project.txt"
pin_file="$config_dir/exporter-version.txt"

die() { printf '\n%s\n' "$*" >&2; exit 1; }
note() { printf '%s\n' "$*" >&2; }

# ---- pinned version -------------------------------------------------------
[[ -f "$pin_file" ]] || die "No $pin_file. It should hold the pinned exporter version."
pinned="$(grep -v '^[[:space:]]*#' "$pin_file" | head -1 | tr -d '[:space:]')"
[[ -n "$pinned" ]] || die "$pin_file is empty."

# ---- project url ----------------------------------------------------------
[[ -f "$project_file" ]] || die "No $project_file. Put the Overleaf project URL in it."
project_url="$(grep -v '^[[:space:]]*#' "$project_file" | head -1 | tr -d '[:space:]')"
[[ "$project_url" =~ ^https:// ]] || die "$project_file does not contain an https URL."
project_id="${project_url##*/project/}"

# ---- isolated venv, installed at the pinned version -----------------------
if [[ ! -x "$venv/bin/overleaf-comments-export" ]]; then
  note "Creating $venv and installing overleaf-comments-export==$pinned"
  python3 -m venv "$venv"
  "$venv/bin/pip" install --quiet --upgrade pip
  "$venv/bin/pip" install --quiet "overleaf-comments-export==$pinned"
fi
installed="$("$venv/bin/overleaf-comments-export" --version | awk '{print $NF}')"
if [[ "$installed" != "$pinned" ]]; then
  note "venv has $installed, $pin_file pins $pinned. Reinstalling the pinned one."
  "$venv/bin/pip" install --quiet --force-reinstall "overleaf-comments-export==$pinned"
  installed="$("$venv/bin/overleaf-comments-export" --version | awk '{print $NF}')"
fi
[[ "$installed" == "$pinned" ]] || die "Could not get $pinned installed (have $installed)."
note "Exporter: overleaf-comments-export $installed (pinned in review/config/exporter-version.txt)"

# ---- session cookie -------------------------------------------------------
have_session() { [[ -n "${OVERLEAF_SESSION:-}" || -s "$session_file" ]]; }

if ! have_session; then
  if [[ "${OCE_INTERACTIVE:-0}" != "1" && ! -t 0 ]]; then
    die "No Overleaf session available.
  Set OVERLEAF_SESSION in the environment, or put the cookie in
    $session_file   (chmod 600; that file is gitignored),
  or run this from a terminal and paste it at the prompt.
Never paste the cookie into a command argument, a file in the repository, or chat."
  fi
  note "Reading the Overleaf session cookie from https://www.overleaf.com"
  note "(DevTools → Application → Storage → Cookies → overleaf_session2)."
  printf 'Paste the cookie value (input hidden): '
  read -r -s OVERLEAF_SESSION
  printf '\n'
  [[ -n "$OVERLEAF_SESSION" ]] || die "Empty cookie."
  export OVERLEAF_SESSION
fi
if [[ -s "$session_file" ]]; then
  OVERLEAF_SESSION="$(head -1 "$session_file")"
  export OVERLEAF_SESSION
fi
# Sanity check that this looks like a session cookie, so a wrong file fails here
# rather than as a confusing Overleaf error later. Nothing is printed.
if [[ ${#OVERLEAF_SESSION} -lt 20 ]]; then
  die "The session value is ${#OVERLEAF_SESSION} characters, which is too short to be an Overleaf session."
fi
note "Session loaded (${#OVERLEAF_SESSION} characters, value not shown)."

# ---- run ------------------------------------------------------------------
# The out directory is a scratch area: review_import.py takes the snapshot that
# gets kept. --no-since because each export lands in its own round; the helper
# does the round-over-round comparison by thread id instead.
mkdir -p "$out_dir"
extra=()
if [[ "${OCE_INCLUDE_SOURCE:-0}" == "1" ]]; then
  # Source snapshots are what make anchors verifiable against the working tree.
  extra+=(--include-source)
fi

exec "$venv/bin/overleaf-comments-export" \
  --project-url "$project_url" \
  --out "$out_dir" \
  --no-since \
  "${extra[@]}" \
  "$@"
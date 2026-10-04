# Review comments in code-server

Fuchs's Overleaf review comments, readable beside the manuscript in VS Code.

Overleaf keeps comment threads in the editor, not in the `.tex` files, so they
never arrive through the Git sync. This folder holds the export route and the
reading view. It is a **one-way snapshot**: replying to or resolving a thread
still happens in Overleaf.

---

## The short version

```bash
# 1. in Chrome, on the open Overleaf project tab: click the extension icon,
#    Export current project.  (Or, see "Exporting from this container".)
# 2. drag the downloaded folder into review/imports-staging/ in the code-server
#    file tree, or scp it in
# 3. import it:
python3 review/bin/review_import.py ~/Downloads/overleaf-comments/<project>/<timestamp>
# 4. read:
#    review/current/comments.md      the comments, grouped by file and section
#    review/current/INDEX.md         one row per thread, keyed by thread id
#    review/notes/TRIAGE.md          your checklist; your notes survive refreshes
```

`review/current/CHANGES.md` appears from the second round on: what is new, what
was replied to, what got resolved, what disappeared. `review/current/PROVENANCE.md`
records which export this is, which exporter version made it, and what could not
be verified.

**Export the comments before you pull manuscript changes from GitHub.** Overleaf
warns that a pull can displace comments and tracked changes; this snapshot is
your copy of them. Fuchs renamed every section file in commit `6c82752`
(`sections/methods.tex` → `sections/3_methods.tex`), which is the kind of rename
that can detach an anchor — so treat quoted text as the address of a comment, not
the line number.

---

## Layout

```
review/
  README.md                 this file
  bin/review_import.py      the import helper (stdlib only, no credentials)
  bin/oce-export.sh         optional: export from inside this container
  config/overleaf-project.txt    the Overleaf project id (not a secret)
  config/exporter-version.txt    pinned exporter version
  config/session-cookie     only if you use the container route (gitignored)
  notes/TRIAGE.md           yours; a generated block in it is refreshed, the rest is not
  imports/<timestamp-label>/ verbatim snapshot of every export, never rewritten
  current/                  the reading view, regenerated on every import
  tools/                    the exporter venv, the fixture generator, the self-check
```

`imports/`, `current/`, `tools/.venv/` and the session cookie are **gitignored**.
The repository is public and the manuscript is not submitted: raw exports carry
unpublished prose and `source/` carries byte-identical copies of the manuscript.
Tracked are this file, `bin/`, `config/` (minus the cookie), `tools/*.py`,
`tools/*.sh` and your `notes/TRIAGE.md` — keep quotes out of that last one.

A refresh can only touch `current/` and the marked block in `notes/TRIAGE.md`.
Snapshots are never overwritten: an import always creates a new
`imports/<timestamp>` directory.

---

## First import (browser extension, recommended)

The extension reads the Overleaf project tab you already have signed in, so your
session cookie never leaves your machine and never comes to this container.

1. Install [overleaf-comments-export](https://chromewebstore.google.com/detail/overleaf-comments-export/nbbappjfcankkjnpbaopjhejgdagaglc)
   in Chrome or Edge. It needs no permissions beyond the open tab.
2. Open the manuscript on Overleaf (the editor URL, not the project list).
3. Click the extension icon → **Export current project** → include resolved
   comments and tracked changes → **Export current project**. Keep the popup open
   until it finishes.
4. Chrome writes `Downloads/overleaf-comments/<project name>/<UTC timestamp>/`
   containing `comments-<date>.md`, `comments.json`, `comments.jsonl`,
   `agents.md`.
5. Get that folder here — drag it into the code-server file tree (create
   `review/imports-staging/` there if it does not exist), or:
   ```bash
   scp -r '~/Downloads/overleaf-comments/Daugherty manuscript/2026-10-03T14-35-27Z' \
       <you>@<this-container>:projects/fresh_daugherty_manuscript/review/imports-staging/
   ```
   (`<this-container>` is `gep@jupyterhub04` — `hostname` here — and
   `~/projects` is the workspace this repository lives in.)
6. `python3 review/bin/review_import.py review/imports-staging/2026-10-03T14-35-27Z --label round-1`
7. Delete `review/imports-staging/` when you are happy (it is gitignored).

The extension writes no `source/` snapshot, so anchors cannot be checked against
the exact text they were written against. The import says so explicitly, in
`PROVENANCE.md`, and still checks every quoted phrase against the manuscript in
this working tree. If you want the stronger check, use the CLI route below.

## Refreshes

Same three steps: export again in Overleaf, transfer the new folder, import it.

```bash
python3 review/bin/review_import.py review/imports-staging/<new-timestamp> --label round-2
```

The import compares against the most recent earlier snapshot by **Overleaf thread
id**, so renumbered `C001`-style labels never show up as changes. Use
`--compare-to <path>` to compare against a specific older round, or
`--compare-to none` to skip the comparison. `--dry-run` reports everything and
writes nothing.

## Exporting from this container (optional)

For when you would rather not move files by hand. The exporter is installed into
`review/tools/.venv` at the version pinned in `config/exporter-version.txt` — not
into any system Python.

```bash
bash review/bin/oce-export.sh --doctor      # check connectivity and cookies
OCE_INCLUDE_SOURCE=1 bash review/bin/oce-export.sh    # export, with source/
python3 review/bin/review_import.py review/tools/oce-out --label round-2
```

Authentication, in order of preference:

- put the cookie in `review/config/session-cookie` (mode 600, gitignored), or
- `OVERLEAF_SESSION=... bash review/bin/oce-export.sh` in the same command, or
- run it from a terminal and paste at the no-echo prompt.

The cookie is passed to the exporter through `OVERLEAF_SESSION`, which the tool
reads itself. It is never passed as `--cookie` (which lands in shell history and
in `ps` for every other process), never written into the repository, and never
printed. Overleaf Git credentials do not work here — this needs a browser
session. `OCE_INCLUDE_SOURCE=1` adds the `source/` snapshot that makes anchor
verification airtight.

Each run writes into `review/tools/oce-out/`; pass any other exporter flag after
the script name, e.g. `bash review/bin/oce-export.sh --reviewer Fuchs`.

---

## Reading and tracking

Open these in order after an import:

| file | what it is |
|---|---|
| `review/current/comments.md` | the readable export: comments next to the words they were written about, replies nested under them, resolved ones struck through |
| `review/current/INDEX.md` | one row per thread — thread id, file:line, section, quoted anchor, reply count, open/resolved |
| `review/notes/TRIAGE.md` | your checklist. Fill in the last column |
| `review/current/CHANGES.md` | what moved since the previous round |
| `review/current/PROVENANCE.md` | which export this is, its exporter version, and every gap found |
| `review/imports/<stamp>/source/` | the manuscript text as it was in Overleaf when the export was taken (CLI route only) |

**Key your notes on the thread id, not on `C001`.** Short ids are assigned in file
then line order, so one new comment near the top renumbers everything below it.
Thread ids are Overleaf's own and stable. `INDEX.md` carries both.

Your entries survive a refresh: the helper reads the last column back before it
rewrites the table. Notes on threads that disappear from the export are kept and
listed separately rather than dropped.

Replying and resolving stays in Overleaf. Address a thread, reply there, resolve
there; the next export will show it as resolved.

---

## What is checked, and what is not

`review_import.py` verifies, and reports:

- `comments.json` parses, carries a `schema_version`, and the project id matches
  `config/overleaf-project.txt` (a mismatch is an error, not a warning to ignore);
- every thread and reply is carried over, resolved threads included;
- each anchored phrase still sits at its recorded offset in the exported source
  snapshot (`text present, offset moved` / `anchor text absent`);
- each anchored phrase is still present in this working tree;
- files in `source/` compared byte-for-byte against the working tree;
- orphan threads (Overleaf returned them, no live anchor) and stale anchors are
  listed, not dropped.

It does **not** and cannot verify that a given git commit is the revision the
comments were written against — the exporter reads comments, ranges and files,
not project history. `PROVENANCE.md` records the Overleaf-side revision as
UNKNOWN on every run. The export timestamp, the exporter version and the local
git HEAD are recorded next to it so you can reason about the gap yourself.

### Limitations worth knowing

- **Anchor drift is expected.** Line numbers refer to the Overleaf-side text at
  export time. The quoted phrase is the reliable handle; `context.before` and
  `context.after` in `comments.json` carry the surrounding text.
- **Renames and moves break location.** Fuchs's `6c82752` renamed every section
  file. An export taken before that carries `sections/methods.tex`, which no
  longer exists here; the import says "plausibly renamed to
  sections/3_methods.tex (not verified)" rather than pretending to resolve it.
- **Orphan and stale threads** have no trustworthy file:line. They are exported
  and kept; the source context and quoted text are all you get.
- **The extension writes no `source/`**, so the strongest anchor check is
  unavailable on that route. The weaker working-tree check still runs.
- **The exporter is unofficial** and uses undocumented Overleaf endpoints
  (`/project/:id/threads`, `/ranges`, the download route). It can break when
  Overleaf changes them. It is read-only, backs off when asked, and identifies
  itself. If it breaks, keep using whatever the last good `imports/` snapshot
  holds, and see the [overleaf-comments-export issues] before assuming the worst.
- **Not a round trip.** Editing the exported Markdown does not reply to,
  resolve, or update anything in Overleaf. There is no write-back path here and
  none is planned without an explicitly authorised, separately verified
  mechanism.
- One-way: comments are snapshots. Anything Fuchs changes in Overleaf after an
  export appears only in the next one.

---

## Upgrading the exporter

```bash
review/tools/.venv/bin/pip install --upgrade "overleaf-comments-export==<new>"
review/tools/.venv/bin/overleaf-comments-export --version
$EDITOR review/config/exporter-version.txt     # put the new version on the pin line
review/tools/check_import.sh                   # re-run the self-check
```

`check_import.sh` builds two synthetic exports with the real exporter, offline, and
runs the import over them: it covers the first import, a refresh with new replies
and resolutions, note preservation, project mismatch, the extension's no-`source/`
shape, and that no manuscript file is touched. It exercises no Overleaf endpoint,
so it says nothing about authentication.

Current state (2026-10-03): exporter 0.22.2 pinned and installed in
`review/tools/.venv`; `check_import.sh` passes; the real project id is
configured. **A real authenticated export has not been imported yet** — the first
one is the browser-extension run in step 1 above.

[overleaf-comments-export issues]: https://github.com/Mangluu/overleaf-comments-export/issues/new/choose
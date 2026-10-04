#!/usr/bin/env python3
r"""Import an Overleaf comment export into review/ without touching the manuscript.

The export is made on the machine where you are signed in to Overleaf (browser
extension, or the CLI on that machine), then copied here. This script:

  1. validates it (comments.json must be the exporter's schema),
  2. keeps a verbatim, immutable snapshot under review/imports/<timestamp>/,
  3. rebuilds the generated reading view under review/current/,
  4. records provenance, including what could NOT be verified,
  5. refreshes a thread-id-keyed block in review/notes/TRIAGE.md, preserving
     your own note cells,
  6. reports missing anchors, orphan threads and stale locations loudly.

It never writes to the manuscript, never talks to Overleaf, and never needs
Overleaf credentials. Standard library only.

    python3 review/bin/review_import.py ~/Downloads/overleaf-comments/My\ Paper/2026-10-03T14-35-27Z
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from collections.abc import Iterable

# Bumped when the generated layout or the meaning of the ledger changes.
IMPORT_FORMAT_VERSION = 1
MIN_SCHEMA_VERSION = "1.0"

TRIAGE_BEGIN = "<!-- BEGIN GENERATED: review_import.py -->"
TRIAGE_END = "<!-- END GENERATED: review_import.py -->"


class ImportError_(RuntimeError):
    """A problem the user can act on, reported without a traceback."""


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def utc_stamp(when: _dt.datetime | None = None) -> str:
    when = when or _dt.datetime.now(_dt.timezone.utc)
    return when.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


_WS = re.compile(r"\s+")


def norm(text: str) -> str:
    """Whitespace-insensitive form, for asking 'is this phrase still there?'."""
    return _WS.sub(" ", text or "").strip()


def truncate(text: str, width: int = 90) -> str:
    text = norm(text).replace("|", "\\|")
    return text if len(text) <= width else text[: width - 1] + "…"


def one_line(text: str | None) -> str:
    """First non-empty line of a reply, for compact tables."""
    if not text:
        return ""
    for line in text.splitlines():
        if line.strip():
            return truncate(line.strip(), 70)
    return ""


# --------------------------------------------------------------------------
# locating and loading the export
# --------------------------------------------------------------------------

def find_export_json(target: Path) -> Path:
    """Accept a folder from either exporter route, or the json file itself."""
    target = target.expanduser()
    if target.is_file():
        return target.resolve()
    if not target.is_dir():
        raise ImportError_(f"No such export: {target}")
    named = target / "comments.json"
    if named.is_file():
        return named.resolve()
    # Browser-extension runs are timestamped folders; anything deeper is fine as
    # long as there is exactly one comments.json to choose from.
    found = sorted(target.rglob("comments.json"))
    if len(found) == 1:
        return found[0].resolve()
    if not found:
        raise ImportError_(
            f"No comments.json under {target}.\n"
            "Point at the folder the exporter wrote (it contains comments.json), "
            "not at the parent Downloads folder."
        )
    listed = "\n".join(f"  {p}" for p in found[:10])
    raise ImportError_(
        f"{len(found)} comments.json files under {target}; pick one:\n{listed}"
    )


def load_export(json_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ImportError_(f"{json_path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ImportError_(f"{json_path} does not contain a JSON object.")

    schema = str(payload.get("schema_version") or "")
    if not schema:
        raise ImportError_(
            f"{json_path} has no schema_version. This does not look like an "
            "overleaf-comments-export file (or it is too old to be usable)."
        )
    if tuple(int(p) for p in schema.split(".") if p.isdigit()) < tuple(
        int(p) for p in MIN_SCHEMA_VERSION.split(".")
    ):
        raise ImportError_(
            f"Export schema is {schema}, older than the {MIN_SCHEMA_VERSION} this "
            "script understands. Re-export with a newer overleaf-comments-export."
        )
    for key in ("comments", "threads"):
        if not isinstance(payload.get(key), list if key == "comments" else dict):
            raise ImportError_(f"{json_path} has no usable '{key}' section.")
    return payload


def read_config_project(config_path: Path) -> str | None:
    if not config_path.is_file():
        return None
    for line in config_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        return line
    return None


def project_id_of(project_url_or_id: str | None) -> str | None:
    if not project_url_or_id:
        return None
    match = re.search(r"/project/([0-9a-zA-Z]+)", project_url_or_id)
    return match.group(1) if match else project_url_or_id.strip() or None


# --------------------------------------------------------------------------
# manuscript state (read-only)
# --------------------------------------------------------------------------

def git_state(repo_root: Path) -> dict[str, Any]:
    """HEAD and dirtiness, for provenance. Never fails the import."""

    def run(args: list[str]) -> str | None:
        try:
            out = subprocess.run(
                ["git", "-C", str(repo_root), *args],
                capture_output=True, text=True, timeout=20, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    head = run(["rev-parse", "HEAD"])
    return {
        "available": head is not None,
        "head": head,
        "short": head[:12] if head else None,
        "branch": run(["rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty_files": len(
            [ln for ln in (run(["status", "--porcelain"]) or "").splitlines() if ln.strip()]
        ),
        "describe": run(["log", "-1", "--format=%h %cI %s"]),
    }


def worktree_path(repo_root: Path, pathname: str | None) -> Path | None:
    if not pathname:
        return None
    candidate = (repo_root / pathname).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError:
        return None  # never read outside the repository
    return candidate if candidate.is_file() else None


def rename_candidates(repo_root: Path, pathname: str | None, limit: int = 3) -> list[str]:
    """Files elsewhere in the tree that look like the missing one after a rename.

    Handles the case that bit us here: `sections/methods.tex` renamed to
    `sections/3_methods.tex` shares no basename, so a plain search finds nothing.
    """
    if not pathname:
        return []
    wanted = Path(pathname)
    exact, fuzzy = [], []
    for p in sorted(repo_root.rglob("*")):
        if not p.is_file() or ".git" in p.parts or "review" in p.parts:
            continue
        rel = str(p.relative_to(repo_root))
        if p.name == wanted.name:
            exact.append(rel)
        elif p.suffix == wanted.suffix and wanted.stem and wanted.stem in p.stem:
            fuzzy.append(rel)
        if len(exact) >= limit:
            break
    return (exact + fuzzy)[:limit]


# --------------------------------------------------------------------------
# anchor verification
# --------------------------------------------------------------------------

class AnchorReport:
    """Where each comment's anchor was checked, and whether it still lines up."""

    def __init__(self) -> None:
        self.in_snapshot: dict[str, str] = {}   # thread_id -> verdict
        self.in_worktree: dict[str, str] = {}   # thread_id -> verdict
        self.worktree_detail: dict[str, str] = {}  # thread_id -> rename hint, etc.
        self.problems: list[str] = []

    def snapshot_tally(self) -> dict[str, int]:
        return _tally(self.in_snapshot)

    def worktree_tally(self) -> dict[str, int]:
        return _tally(self.in_worktree)


def _tally(verdicts: dict[str, str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for verdict in verdicts.values():
        out[verdict] = out.get(verdict, 0) + 1
    return out


def verify_anchors(
    payload: dict[str, Any], export_dir: Path, repo_root: Path, source_dir: Path | None
) -> AnchorReport:
    report = AnchorReport()
    for comment in payload.get("comments", []):
        tid = comment.get("thread_id") or comment.get("short_id") or "?"
        pathname = comment.get("pathname")
        anchor = comment.get("anchored_text") or ""
        offset = comment.get("offset")

        # (a) against the source snapshot shipped with the export
        if source_dir is None:
            report.in_snapshot[tid] = "no source snapshot in export"
        elif not pathname:
            report.in_snapshot[tid] = "comment has no pathname"
        else:
            snap_file = source_dir / pathname
            if not snap_file.is_file():
                report.in_snapshot[tid] = f"snapshot has no {pathname}"
                report.problems.append(
                    f"thread {tid}: export claims {pathname} but source/ has no such file"
                )
            else:
                text = snap_file.read_text(encoding="utf-8", errors="replace")
                report.in_snapshot[tid] = _check_text(text, anchor, offset)
                if report.in_snapshot[tid] != "anchor matches offset":
                    stale_note = (
                        " (the exporter flags this one as stale too)"
                        if comment.get("stale") else ""
                    )
                    report.problems.append(
                        f"thread {tid}: anchor does not match source/{pathname} "
                        f"({report.in_snapshot[tid]}){stale_note}"
                    )

        # (b) against the manuscript as it stands in this working tree
        if not pathname:
            report.in_worktree[tid] = "comment has no pathname"
        else:
            local = worktree_path(repo_root, pathname)
            if local is None:
                cands = rename_candidates(repo_root, pathname)
                hint = f" — plausibly renamed to {', '.join(cands)} (not verified)" if cands else ""
                report.in_worktree[tid] = "file missing in working tree"
                report.worktree_detail[tid] = hint.strip(" —") or "file not present under that name"
                report.problems.append(
                    f"thread {tid}: {pathname} is not in the working tree{hint}"
                )
            else:
                text = local.read_text(encoding="utf-8", errors="replace")
                report.in_worktree[tid] = _check_text(text, anchor, None)

    return report


def _check_text(text: str, anchor: str, offset: Any) -> str:
    if not anchor:
        return "comment has no anchored text"
    if isinstance(offset, int) and offset >= 0:
        if text[offset: offset + len(anchor)] == anchor:
            return "anchor matches offset"
        if norm(anchor) in norm(text):
            return "text present, offset moved"
        return "anchor text absent"
    return "anchor present" if norm(anchor) in norm(text) else "anchor text absent"


# --------------------------------------------------------------------------
# snapshot of the raw export
# --------------------------------------------------------------------------

def snapshot_export(
    export_dir: Path, imports_root: Path, label: str | None, force: bool, dry_run: bool
) -> Path:
    stamp = utc_stamp()
    name = f"{stamp}-{slug(label)}" if label else stamp
    dest = imports_root / name
    if dest.exists():
        if not force:
            raise ImportError_(
                f"{dest} already exists. Imports are kept verbatim and never "
                "overwritten; pass --force only if you know it is a duplicate."
            )
        if not dry_run:
            shutil.rmtree(dest)
    if dry_run:
        return dest
    dest.mkdir(parents=True)
    for item in sorted(export_dir.iterdir()):
        if item.name == "comments.log":
            continue  # scratch log; the export itself is what we keep
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    return dest


def slug(text: str | None) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")
    return cleaned[:48].lower()


# --------------------------------------------------------------------------
# thread ledger
# --------------------------------------------------------------------------

def build_ledger(
    payload: dict[str, Any], imports_root: Path | None = None, exclude: Path | None = None,
    scan: bool = True,
) -> dict[str, Any]:
    """One record per Overleaf thread, keyed by the durable Overleaf thread id.

    Short ids (C001 …) are positional and renumber when new comments arrive, so
    they are recorded as a history, never as the key.
    """
    threads = payload.get("threads") or {}
    comments_by_thread: dict[str, list[dict[str, Any]]] = {}
    for comment in payload.get("comments", []):
        comments_by_thread.setdefault(comment.get("thread_id"), []).append(comment)

    history = scan_history(imports_root, exclude) if (scan and imports_root) else {}

    records: dict[str, Any] = {}
    for tid, thread in threads.items():
        anchors = comments_by_thread.get(tid, [])
        primary = anchors[0] if anchors else {}
        messages = thread.get("messages") or []
        seen = history.get(tid)
        records[tid] = {
            "thread_id": tid,
            "short_ids": sorted(c.get("short_id") for c in anchors if c.get("short_id")),
            "pathname": primary.get("pathname"),
            "line": primary.get("line"),
            "nearest_heading": primary.get("nearest_heading"),
            "enclosing_float": primary.get("enclosing_float"),
            "anchored_text": primary.get("anchored_text"),
            "stale_anchor": bool(primary.get("stale")),
            "resolved": bool(thread.get("resolved")),
            "resolved_at": thread.get("resolved_at"),
            "message_count": len(messages),
            "reply_count": len(messages) - 1,
            "reviewers": sorted(
                {
                    (m.get("user") or {}).get("name") or (m.get("user") or {}).get("id") or "?"
                    for m in messages
                }
            ),
            "first_message_at": messages[0].get("timestamp") if messages else None,
            "last_activity_at": messages[-1].get("timestamp") if messages else None,
            "root_comment": one_line(messages[0].get("content") if messages else None),
            "last_reply": one_line(messages[-1].get("content") if len(messages) > 1 else None),
            "anchored_to_live_source": tid not in set(payload.get("orphan_thread_ids") or []),
            "first_seen_import": (seen or [None])[0],
            "imports_seen": len(seen or []) + 1,
        }
    return {"format_version": IMPORT_FORMAT_VERSION, "threads": records}


def scan_history(imports_root: Path, exclude: Path | None) -> dict[str, list[str]]:
    """thread_id -> [import dir names], oldest first, from earlier snapshots."""
    history: dict[str, list[str]] = {}
    if not imports_root.is_dir():
        return history
    for snap in sorted(imports_root.iterdir()):
        if not snap.is_dir() or snap == exclude:
            continue
        js = snap / "comments.json"
        if not js.is_file():
            continue
        try:
            payload = json.loads(js.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for tid in (payload.get("threads") or {}):
            history.setdefault(tid, []).append(snap.name)
    return history


# --------------------------------------------------------------------------
# cross-export comparison (thread ids, so renumbering is never reported)
# --------------------------------------------------------------------------

def compare_exports(
    current: dict[str, Any],
    previous: dict[str, Any],
    current_changes: list[dict[str, Any]] | None = None,
    previous_changes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cur_threads = current.get("threads") or {}
    prev_threads = previous.get("threads") or {}
    out: dict[str, Any] = {
        "new_threads": [],
        "gone_threads": [],
        "new_replies": [],
        "edited_comments": [],
        "resolved": [],
        "reopened": [],
        "new_tracked_changes": [],
    }
    for tid, thread in cur_threads.items():
        before = prev_threads.get(tid)
        if before is None:
            out["new_threads"].append(_thread_stub(tid, thread))
            continue
        if (thread.get("message_count") or 0) > (before.get("message_count") or 0):
            out["new_replies"].append(
                {
                    **_thread_stub(tid, thread),
                    "new_messages": (thread.get("message_count") or 0)
                    - (before.get("message_count") or 0),
                    "latest": one_line(thread.get("last_reply")),
                }
            )
        if thread.get("root_comment") and before.get("root_comment") and (
            thread["root_comment"] != before["root_comment"]
        ):
            out["edited_comments"].append(
                {
                    **_thread_stub(tid, thread),
                    "now": thread.get("root_comment"),
                    "before": before.get("root_comment"),
                }
            )
        if thread.get("resolved") and not before.get("resolved"):
            out["resolved"].append(_thread_stub(tid, thread))
        elif before.get("resolved") and not thread.get("resolved"):
            out["reopened"].append(_thread_stub(tid, thread))

    for tid in prev_threads:
        if tid not in cur_threads:
            out["gone_threads"].append(_thread_stub(tid, prev_threads[tid]))

    # Tracked changes are matched on what they are, not on an id: the exporter
    # leaves `id` empty whenever Overleaf does not send one, so several changes
    # can share the same (empty) id and an id-based diff would report nothing.
    prev_keys = {_change_key(c) for c in (previous_changes or [])}
    for change in current_changes or []:
        if _change_key(change) not in prev_keys:
            out["new_tracked_changes"].append(
                {
                    "short_id": change.get("short_id"),
                    "pathname": change.get("pathname"),
                    "line": change.get("line"),
                    "kind": change.get("kind"),
                    "content": truncate(change.get("content") or "", 70),
                }
            )
    return out


def _change_key(change: dict[str, Any]) -> tuple[Any, ...]:
    return (
        change.get("pathname"),
        change.get("kind"),
        change.get("offset"),
        norm(change.get("content") or ""),
    )


def _thread_stub(tid: str, thread: dict[str, Any]) -> dict[str, Any]:
    return {
        "thread_id": tid,
        "short_ids": thread.get("short_ids") or [],
        "pathname": thread.get("pathname"),
        "line": thread.get("line"),
        "anchored_text": truncate(thread.get("anchored_text") or "", 60),
        "resolved": bool(thread.get("resolved")),
    }


# --------------------------------------------------------------------------
# generated markdown
# --------------------------------------------------------------------------

def write_provenance(
    path: Path, payload: dict[str, Any], export_dir: Path, snap: Path,
    json_path: Path, markdown: Path | None, repo_root: Path, git: dict[str, Any],
    anchors: AnchorReport, source_dir: Path | None, comparison: dict[str, Any] | None,
    config_project: str | None, gaps: list[str],
) -> None:
    def rel(p: Path | None) -> str | None:
        """Repo-relative where possible: absolute paths make the report noisy."""
        if p is None:
            return None
        try:
            return p.relative_to(repo_root).as_posix()
        except ValueError:
            return p.as_posix()
    summary = payload.get("summary") or {}
    project = payload.get("project") or {}
    pulled = payload.get("pulled_at")
    when = f"`{pulled}` (recorded by the exporter)" if pulled else (
        f"**UNKNOWN in the export** — file mtime {utc_stamp_from_mtime(json_path)} "
        "used as a fallback (the browser extension does not write `pulled_at`)"
    )
    export_id = project.get("id")
    config_id = project_id_of(config_project)

    lines: list[str] = []
    lines += [
        "# Provenance and health of this export",
        "",
        "Generated by `review/bin/review_import.py`. Everything below is derived "
        "from the export itself and from this working tree; nothing here was "
        "assumed.",
        "",
        "## The export",
        "",
        f"- **Snapshot kept at:** `{rel(snap)}` (verbatim copy, never rewritten)",
        f"- **Read from:** `{rel(json_path)}`",
        f"- **Markdown file:** {f'`{markdown.name}`' if markdown else '**absent**'}",
        f"- **Exported at:** {when}",
        f"- **Exporter version (`tool_version`):** `{payload.get('tool_version') or 'UNKNOWN'}`",
        f"- **Export schema:** `{payload.get('schema_version')}`",
        f"- **Overleaf project:** `{export_id or 'UNKNOWN'}`"
        + (f" — {project.get('title')}" if project.get("title") else ""),
        f"- **sha256 of comments.json:** `{sha256_file(json_path)}`",
    ]
    if config_id:
        match = "matches" if config_id == export_id else "**DOES NOT MATCH**"
        lines.append(
            f"- **Configured project** (`review/config/overleaf-project.txt`): "
            f"`{config_id}` — {match} the export"
        )
    else:
        lines.append("- **Configured project:** none configured (UNKNOWN)")

    lines += [
        "",
        "## The manuscript in this container",
        "",
        f"- **Repository:** `{rel(repo_root)}` (this file lives at `review/current/`, "
        "so paths are relative to it)",
        f"- **Git HEAD:** "
        f"{_code(git.get('head')) if git.get('available') else '**not a git repository**'}",
        f"- **Short / describe:** {_code(git.get('describe')) or 'UNKNOWN'}",
        f"- **Branch:** {('`' + str(git.get('branch')) + '`') if git.get('branch') else 'UNKNOWN'}",
        f"- **Uncommitted changes:** {git.get('dirty_files', 'UNKNOWN')}",
        "- **Overleaf-side revision:** **UNKNOWN.** The exporter reads comments, "
        "ranges and files; it does not read project history, and neither does "
        "this script. Nothing here should be read as 'the git commit above is the "
        "revision these comments were written against'.",
        "",
        "## Does this export match the working tree?",
        "",
    ]
    lines += _source_comparison_table(source_dir, repo_root)

    lines += [
        "",
        "## Completeness",
        "",
        f"- Threads: **{summary.get('thread_count', '?')}** "
        f"(open {summary.get('open_count', '?')}, resolved {summary.get('resolved_count', '?')})",
        f"- Comments with an anchor: **{len(payload.get('comments') or [])}**",
        f"- Tracked changes: **{summary.get('tracked_change_count', '?')}**",
        f"- Files touched: **{summary.get('file_count', '?')}**",
        f"- Reviewers: **{summary.get('reviewer_count', '?')}**",
        f"- Orphan threads (returned by Overleaf, no live anchor): "
        f"**{len(payload.get('orphan_thread_ids') or [])}**"
        + (
            " — " + ", ".join(f"`{t}`" for t in payload["orphan_thread_ids"][:12])
            if payload.get("orphan_thread_ids")
            else ""
        ),
        f"- Stale anchors: **{summary.get('stale_anchor_count', '?')}**",
        "",
        "### Anchor checks",
        "",
        f"Against the export's own `source/` snapshot: {_tally_line(anchors.snapshot_tally())}",
        "",
        f"Against the working tree as it is now: {_tally_line(anchors.worktree_tally())}",
        "",
    ]

    if gaps:
        lines += ["### Gaps to be aware of", ""]
        lines += _grouped_gaps(gaps)
        lines += [""]
    else:
        lines += ["### Gaps to be aware of", "", "- None reported by this import.", ""]

    lines += [
        "## Changes since the previous import",
        "",
    ]
    if comparison is None:
        lines.append(
            "No previous import was available to compare with, so nothing is "
            "reported here. The next import will fill this in."
        )
    else:
        counts = {k: len(v) for k, v in comparison.items()}
        lines.append(
            "Compared against the previous snapshot in `review/imports/`, keyed by "
            "Overleaf thread id (short ids such as `C001` are positional and are "
            "not used for this)."
        )
        lines.append("")
        lines.append(
            "  " + ", ".join(f"{k.replace('_', ' ')}: **{n}**" for k, n in counts.items())
        )
        lines.append("")
        lines.append("See `CHANGES.md` for the detail.")
    lines += ["", "---", "", "Reading order: `comments.md` → `INDEX.md` → "
              "`TRIAGE.md` in `review/notes/`.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def utc_stamp_from_mtime(path: Path) -> str:
    return utc_stamp(_dt.datetime.fromtimestamp(path.stat().st_mtime, _dt.timezone.utc))


def _code(value: Any) -> str:
    return f"`{value}`" if value else "UNKNOWN"


def _grouped_gaps(gaps: list[str], examples: int = 3) -> list[str]:
    """One bullet per distinct problem, with a count and a few examples.

    A review round can produce hundreds of per-thread gap lines; listing them all
    turns the report into noise and hides the things that matter.
    """
    grouped: dict[str, list[str]] = {}
    for gap in gaps:
        # Strip the leading thread id so the same problem groups together.
        key = re.sub(r"^thread [^:]+: ", "", gap)
        key = re.sub(r"`[^`]+`", "`…`", key)
        grouped.setdefault(key, []).append(gap)
    out: list[str] = []
    for key, items in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        if len(items) == 1:
            out.append(f"- {items[0]}")
            continue
        out.append(f"- {key} ({len(items)} of them)")
        for item in items[:examples]:
            out.append(f"  - e.g. {item}")
        if len(items) > examples:
            out.append(f"  - … and {len(items) - examples} more like these")
    return out


def _tally_line(tally: dict[str, int]) -> str:
    if not tally:
        return "nothing to check."
    return "; ".join(f"{v} {k}" for k, v in sorted(tally.items(), key=lambda kv: -kv[1]))


def _source_comparison_table(source_dir: Path | None, repo_root: Path) -> list[str]:
    if source_dir is None or not source_dir.is_dir():
        return [
            "**UNKNOWN.** This export carries no `source/` directory, so there is "
            "nothing to compare against the working tree. This is what the browser "
            "extension produces. Re-export with the Python CLI and "
            "`--include-source` to get one.",
        ]
    rows = ["| file in export | in working tree | identical |", "|---|---|---|"]
    files = sorted(p for p in source_dir.rglob("*") if p.is_file())
    if not files:
        return ["**EMPTY.** The export's `source/` directory has no files in it."]
    for path in files:
        rel = path.relative_to(source_dir).as_posix()
        local = worktree_path(repo_root, rel)
        if local is None:
            cands = rename_candidates(repo_root, rel)
            state = "**no**"
            note = f"missing here{f' (renamed? {", ".join(cands)})' if cands else ''}"
        elif sha256_file(local) == sha256_file(path):
            state = "yes"
            note = "identical"
        else:
            state = "yes"
            note = "**differs — edited locally since this export**"
        rows.append(f"| `{rel}` | {state} | {note} |")
    rows += [
        "",
        "A *differs* row is expected and is not an error: it means the manuscript "
        "moved on since the export was taken, which is why anchors are recorded as "
        "quoted text as well as line numbers.",
    ]
    return rows


def write_index(path: Path, ledger: dict[str, Any], payload: dict[str, Any], snap: Path,
                repo_root: Path) -> None:
    records = sorted(
        ledger["threads"].values(),
        key=lambda r: (r.get("pathname") or "~", r.get("line") or 0),
    )
    open_n = sum(1 for r in records if not r["resolved"])
    res_n = len(records) - open_n
    lines = [
        "# Thread index — keyed by Overleaf thread id",
        "",
        f"{len(records)} threads in this export ({open_n} open, {res_n} resolved).",
        "",
        "Use the **`thread_id`** column in `review/notes/TRIAGE.md`. The `short id` "
        "column (`C001`, …) is positional: it is renumbered whenever a new comment "
        "lands earlier in the document, so it is for reading the Markdown only.",
        "",
        "| thread_id | short id | file : line | section | anchored text | replies "
        "| state | last activity |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for rec in records:
        short = ", ".join(rec["short_ids"]) or "—"
        where = (
            f"`{rec['pathname']}`:{rec['line']}" if rec.get("pathname") else "— no file —"
        )
        heading = truncate(rec.get("nearest_heading") or "", 40) or "—"
        anchor = truncate(rec.get("anchored_text") or "", 60) or "—"
        if rec.get("stale_anchor"):
            anchor += " ⚠stale"
        if not rec.get("anchored_to_live_source"):
            anchor += " ⚠orphan"
        state = "resolved" if rec["resolved"] else "open"
        last = (rec.get("last_activity_at") or "—")[:10]
        lines.append(
            f"| `{rec['thread_id']}` | {short} | {where} | {heading} | "
            f"{anchor} | {rec['reply_count']} | {state} | {last} |"
        )
    try:
        json_ref = (snap / "comments.json").relative_to(repo_root).as_posix()
        source_ref = (snap / "source").relative_to(repo_root).as_posix()
    except ValueError:
        json_ref = (snap / "comments.json").as_posix()
        source_ref = (snap / "source").as_posix()
    lines += [
        "",
        "Full thread text, replies and the quoted passage around each anchor are in "
        f"`comments.md` and in `{json_ref}`. The manuscript text as it was in "
        f"Overleaf at export time is under `{source_ref}` when the export carried it.",
        "",
        "This index is regenerated on every import; your own notes are not kept here "
        "— they are in `../notes/TRIAGE.md`, keyed by the same thread id.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_changes(path: Path, comparison: dict[str, Any], previous_name: str) -> None:
    labels = {
        "new_threads": "New threads",
        "gone_threads": "Threads no longer in the export (usually deleted in Overleaf)",
        "new_replies": "Threads with new replies",
        "edited_comments": "Comments edited after you last saw them",
        "resolved": "Marked resolved since the last import",
        "reopened": "Reopened since the last import",
        "new_tracked_changes": "New tracked changes",
    }
    lines = [
        "# What changed since the previous import",
        "",
        f"Previous import: `{previous_name}`. Compared by Overleaf **thread id**, so "
        "renumbered display labels do not show up as changes.",
        "",
    ]
    empty = True
    for key, label in labels.items():
        items: list[dict[str, Any]] = comparison.get(key) or []
        if not items:
            continue
        empty = False
        lines += [f"## {label} ({len(items)})", ""]
        for item in items:
            bits = [f"`{item.get('thread_id')}`"]
            if item.get("short_ids"):
                bits.append(f"({', '.join(item['short_ids'])})")
            if item.get("pathname"):
                bits.append(f"in `{item['pathname']}`")
            if item.get("line"):
                bits.append(f"line {item['line']}")
            if item.get("anchored_text") and item["anchored_text"] != "—":
                bits.append(f"on “{item['anchored_text']}”")
            lines.append("- " + " ".join(str(b) for b in bits))
            if item.get("new_messages"):
                lines.append(f"  - {item['new_messages']} new message(s): {item.get('latest')}")
            if item.get("now"):
                lines.append(f"  - now: {item['now']}")
                lines.append(f"  - before: {item.get('before')}")
            if item.get("kind"):
                lines.append(f"  - {item['kind']}: {item.get('content')}")
        lines.append("")
    if empty:
        lines += ["Nothing changed between these two exports.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------
# TRIAGE.md: a generated block, with the user's own cells preserved
# --------------------------------------------------------------------------

def read_existing_notes(triage: Path) -> dict[str, str]:
    """thread_id -> the user's own cell, from the previous generated block."""
    if not triage.is_file():
        return {}
    text = triage.read_text(encoding="utf-8")
    if TRIAGE_BEGIN not in text or TRIAGE_END not in text:
        return {}
    block = text.split(TRIAGE_BEGIN, 1)[1].split(TRIAGE_END, 1)[0]
    notes: dict[str, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|") or "thread_id" in line:
            continue
        first = line.strip("|").split("|", 1)[0].strip()
        if not first or set(first) <= set("-: "):
            continue  # table separator row
        # Split the user's note off from the right, so a "|" typed inside a note
        # does not shift the columns.
        rest, _, note = line.strip("|").rpartition("|")
        tid = rest.split("|", 1)[0].strip().strip("` ")
        if tid and tid != "—" and note.strip():
            notes[tid] = note.strip()
    return notes


def update_triage(
    triage: Path, ledger: dict[str, Any], payload: dict[str, Any], snap: Path, notes: dict[str, str]
) -> None:
    records = sorted(
        ledger["threads"].values(),
        key=lambda r: (r.get("pathname") or "~", r.get("line") or 0),
    )
    orphans = set(payload.get("orphan_thread_ids") or [])

    rows = []
    for rec in records:
        tid = rec["thread_id"]
        short = ", ".join(rec["short_ids"]) or "—"
        where = f"`{rec['pathname']}`:{rec['line']}" if rec.get("pathname") else "— no file —"
        anchor = truncate(rec.get("anchored_text") or "", 70) or "—"
        state = "resolved" if rec["resolved"] else "open"
        flags = []
        if rec.get("stale_anchor"):
            flags.append("stale anchor")
        if tid in orphans:
            flags.append("orphan (no live anchor)")
        if rec.get("reply_count"):
            flags.append(f"{rec['reply_count']} repl{'y' if rec['reply_count'] == 1 else 'ies'}")
        note = notes.get(tid, "")
        rows.append(
            f"| `{tid}` | {short} | {where} | {anchor} | {state} | "
            f"{'; '.join(flags) or '—'} | {note} |"
        )

    gone_rows = []
    for tid, note in notes.items():
        if tid not in ledger["threads"] and note:
            gone_rows.append(
                f"| `{tid}` | — | — | — | — | not in the latest export | {note} |"
            )

    open_n = sum(1 for r in records if not r["resolved"])
    res_n = len(records) - open_n
    block = [
        TRIAGE_BEGIN,
        "",
        "<!-- Generated by review/bin/review_import.py. Rewritten on every import; "
        "your entries in the last column are read back and preserved. Text outside "
        "these markers is never touched. -->",
        "",
        f"Export `{snap.name}`: **{len(records)} threads** "
        f"({open_n} open, {res_n} resolved).",
        "",
        "| thread_id | short id | file : line | anchored text | state | flags | my disposition |",
        "|---|---|---|---|---|---|---|",
        *rows,
    ]
    if gone_rows:
        block += ["", "Kept from earlier imports even though they are not in the "
                      "latest export:", "", *gone_rows]
    block += ["", TRIAGE_END]

    text = ""
    if triage.is_file():
        text = triage.read_text(encoding="utf-8")
    if TRIAGE_BEGIN in text and TRIAGE_END in text:
        head, rest = text.split(TRIAGE_BEGIN, 1)
        _, tail = rest.split(TRIAGE_END, 1)
        text = head + "\n".join(block) + tail
    else:
        text = text.rstrip("\n") + ("\n\n" if text.strip() else "") + "\n".join(block) + "\n"
    triage.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def find_previous_snapshot(imports_root: Path, current: Path | None) -> Path | None:
    if not imports_root.is_dir():
        return None
    snaps = [
        p for p in sorted(imports_root.iterdir())
        if p.is_dir() and (current is None or p != current) and (p / "comments.json").is_file()
    ]
    return snaps[-1] if snaps else None


def do_import(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).expanduser().resolve()
    review_root = repo_root / "review"
    imports_root = review_root / "imports"
    current_root = review_root / "current"
    triage = review_root / "notes" / "TRIAGE.md"
    config_path = (
        Path(args.config).expanduser()
        if args.config
        else review_root / "config" / "overleaf-project.txt"
    )

    json_path = find_export_json(Path(args.export))
    export_dir = json_path.parent
    payload = load_export(json_path)
    markdown = next(
        (p for p in sorted(export_dir.glob("comments*.md")) if p.is_file()), None
    )
    source_dir = export_dir / "source"
    if not source_dir.is_dir():
        source_dir = None

    config_project = read_config_project(config_path)
    export_id = (payload.get("project") or {}).get("id")
    config_id = project_id_of(config_project)
    gaps: list[str] = []
    if config_id and export_id and config_id != export_id:
        gaps.append(
            f"**Project mismatch.** The export is for `{export_id}` but "
            f"`{config_path.name}` says `{config_id}`. Wrong paper, or stale config."
        )
    if not config_id:
        gaps.append(
            f"No project configured in `{config_path}`, so the export's project id "
            f"(`{export_id or 'UNKNOWN'}`) could not be checked against anything."
        )

    snapshot = snapshot_export(
        export_dir, imports_root, args.label, args.force, args.dry_run
    )

    if args.compare_to == "none":
        previous = None
    elif args.compare_to == "auto":
        previous = find_previous_snapshot(imports_root, snapshot)
    else:
        candidate = Path(args.compare_to).expanduser()
        if candidate.is_file():
            previous = candidate.parent
        elif candidate.is_dir():
            previous = candidate
        else:
            raise ImportError_(f"--compare-to path does not exist: {candidate}")

    previous_payload = None
    if previous is not None and (previous / "comments.json").is_file():
        try:
            previous_payload = json.loads((previous / "comments.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            gaps.append(f"Previous import `{previous.name}` could not be read ({exc}).")

    # Both sides of the comparison go through the same normaliser, so the
    # comparison is between two ledgers and not between a ledger and raw
    # exporter JSON.
    previous_ledger = (
        build_ledger(previous_payload, imports_root, snapshot, scan=False)
        if previous_payload is not None
        else None
    )
    current_ledger = build_ledger(payload, imports_root, snapshot)
    comparison = (
        compare_exports(
            current_ledger,
            previous_ledger,
            payload.get("tracked_changes") or [],
            (previous_payload or {}).get("tracked_changes") or [],
        )
        if previous_ledger is not None
        else None
    )

    ledger = current_ledger
    anchors = verify_anchors(payload, export_dir, repo_root, source_dir)
    gaps.extend(anchors.problems)

    summary = payload.get("summary") or {}
    if (payload.get("orphan_thread_ids") or []):
        gaps.append(
            f"{len(payload['orphan_thread_ids'])} thread(s) are not anchored to live "
            "source. They are exported and kept, but the file/line cannot be trusted."
        )
    if summary.get("stale_anchor_count"):
        gaps.append(
            f"{summary['stale_anchor_count']} anchor(s) are stale: the commented text "
            "moved or was deleted in Overleaf. Quoted text is preserved; the line "
            "number is not."
        )
    if markdown is None:
        gaps.append("No Markdown file came with this export; reading view is JSON only.")
    unplaced = [c for c in (payload.get("comments") or []) if not c.get("pathname")]
    if unplaced:
        gaps.append(
            f"{len(unplaced)} comment(s) came with no file name at all, so they "
            "cannot be located in the manuscript. Overleaf's ranges endpoint was "
            "probably unavailable for this run."
        )
    if source_dir is None:
        gaps.append(
            "No `source/` snapshot in this export, so anchors could not be verified "
            "against the exact text they were written against."
        )

    if args.dry_run:
        print(f"[dry-run] would snapshot {export_dir} -> {snapshot}")
        for gap in gaps:
            print(f"  GAP: {gap}")
        return 0

    git = git_state(repo_root)
    current_root.mkdir(parents=True, exist_ok=True)
    for stale in current_root.glob("*"):
        if stale.is_file():
            stale.unlink()

    ledger_out = current_root / "threads.json"
    ledger_out.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    write_index(current_root / "INDEX.md", ledger, payload, snapshot, repo_root)
    if markdown is not None:
        shutil.copy2(markdown, current_root / "comments.md")
    if comparison is not None and previous is not None:
        write_changes(current_root / "CHANGES.md", comparison, previous.name)
    else:
        (current_root / "CHANGES.md").unlink(missing_ok=True)

    notes = read_existing_notes(triage)
    update_triage(triage, ledger, payload, snapshot, notes)

    write_provenance(
        current_root / "PROVENANCE.md", payload, export_dir, snapshot, json_path,
        markdown, repo_root, git, anchors, source_dir, comparison, config_project, gaps,
    )

    print(f"Snapshot kept:  {snapshot}")
    reading_view = current_root / "comments.md" if markdown else current_root / "INDEX.md"
    print(f"Reading view:   {reading_view}")
    print(f"Provenance:     {current_root / 'PROVENANCE.md'}")
    print(f"Triage sheet:   {triage}")
    if comparison is not None:
        print(f"Changes:        {current_root / 'CHANGES.md'}")
    print(
        f"Threads: {summary.get('thread_count', '?')} "
        f"({summary.get('open_count', '?')} open, {summary.get('resolved_count', '?')} resolved), "
        f"tracked changes {summary.get('tracked_change_count', '?')}"
    )
    if gaps:
        print(
            f"\n{len(gaps)} thing(s) to be aware of — full list in PROVENANCE.md:",
            file=sys.stderr,
        )
        for bullet in _grouped_gaps(gaps, examples=2):
            print(f"  {bullet}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Import an Overleaf comment export into review/ without touching the "
            "manuscript. Standard library only; no Overleaf credentials needed."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  review_import.py ~/Downloads/overleaf-comments/'My Paper'/2026-10-03T14-35-27Z\n"
            "  review_import.py ./review/tools/oce-out --label round-2\n"
            "  review_import.py ./export --compare-to review/imports/2026-09-30T18-02-11Z\n"
            "  review_import.py ./export --dry-run\n"
        ),
    )
    p.add_argument("export", help="Export folder (containing comments.json) or the json file")
    p.add_argument(
        "--repo-root", default=str(Path(__file__).resolve().parents[2]),
        help="Manuscript repository root (default: the repo this script lives in)",
    )
    p.add_argument("--config", default=None, help="overleaf-project.txt (default: review/config/)")
    p.add_argument("--label", default=None, help="Short tag for this round, e.g. round-2")
    p.add_argument(
        "--compare-to", default="auto",
        help="'auto' (previous snapshot), 'none', or a path to an earlier export",
    )
    p.add_argument("--force", action="store_true", help="Overwrite an existing snapshot dir")
    p.add_argument("--dry-run", action="store_true", help="Validate and report, write nothing")
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        return do_import(args)
    except ImportError_ as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped. Nothing was written.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())


#!/usr/bin/env python3
"""Make a SYNTHETIC overleaf-comments-export export, offline, for testing the import.

This exists so `review/bin/review_import.py` can be exercised against genuine
exporter output — real Markdown rendering, real `comments.json` schema — without
any Overleaf account and without touching the manuscript. The exporter is
driven in-process with a stand-in for `OverleafClient`, which is the same
technique the exporter's own test suite uses.

Nothing here is real: the paper is invented, the reviewers are invented, the
Overleaf endpoints are never called. A run of this proves the *import* works; it
proves nothing about authentication, Overleaf's endpoints, or the real
manuscript's comments.

    review/tools/.venv/bin/python review/tools/make-fixture-export.py --help
    review/tools/.venv/bin/python review/tools/make_fixture_export.py \\
        --out /tmp/oce-fixture/round-1 --paper /tmp/oce-fixture/paper --round 1

Round 2 evolves the state (new thread, new reply, a resolution, an edited
comment, edited source) so the round-over-round comparison has something to
find. Round 1 deliberately names its section file `sections/methods.tex` while
the generated paper calls it `sections/3_methods.tex`, which is the same
rename-drift situation this repository is actually in.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

PROJECT_ID = "abcdef0123456789abcdef01"  # 24 hex chars, as the exporter insists on
PROJECT_URL = f"https://www.overleaf.com/project/{PROJECT_ID}"

MAIN_TEX = """\\documentclass[12pt]{article}
\\usepackage{graphicx}
\\title{A Synthetic Paper Used Only To Test The Review Import}
\\author{A. Author \\and B. Coauthor}

\\begin{document}
\\maketitle

\\section{Introduction}
% anchor-intro
Nothing in this document is real. The words {decline more slowly than they rise}
were chosen because a reviewer comment sits on them.

\\input{sections/3_methods}

\\section{Conclusion}
% anchor-conclusion
Synthetic conclusion text.
\\end{document}
"""

METHODS_TEX = """\\subsection{Setup}
% anchor-methods
We ran the synthetic benchmark with a declining allowance of
$\\mathrm{NDY}_t = a - b t$ under the fixture grid.
% anchor-reward
The filler channel relaxes the floor whenever realised value is negative,
which is why the fixture reports {persistence rather than disappearance}.
% anchor-truncated
A paragraph long enough that a short context window cuts it off mid sentence, so
the saved source matters for reading what the comment is about.
"""

RESULTS_TEX = """\\subsection{Extension results}
% anchor-results
Occurrence is {rate-independent under constant rates} in the fixture grid.
\\begin{figure}[htbp]
\\centering
\\includegraphics[width=0.6\\textwidth]{figures/placeholder.pdf}
\\caption{A synthetic figure caption that exists only to give a comment a float to sit in.}
\\label{fig:fixture}
\\end{figure}
"""

PAPER: dict[str, str] = {
    "main.tex": MAIN_TEX,
    "sections/3_methods.tex": METHODS_TEX,
    "sections/4_results.tex": RESULTS_TEX,
    "figures/placeholder.pdf": "%PDF-1.4 not a real figure\n",
}

# Old, pre-rename names: what an export taken before the section files were
# renumbered would carry.
SOURCE_NAMES_ROUND_1 = {
    "doc-main": "main.tex",
    "doc-methods": "sections/methods.tex",
    "doc-results": "sections/results.tex",
}
SOURCE_NAMES_ROUND_2 = {
    "doc-main": "main.tex",
    "doc-methods": "sections/3_methods.tex",
    "doc-results": "sections/4_results.tex",
}

F1 = 1_767_225_600_000  # 2026-01-01T00:00:00Z, arbitrary but fixed
HOUR = 3_600_000


def _msg(mid: str, text: str, user: str, email: str, ts: int, edited: int | None = None) -> dict[str, Any]:
    return {
        "id": mid,
        "content": text,
        "timestamp": ts,
        "user_id": f"u-{user}",
        "user": {"name": user, "email": email},
        **({"edited_at": edited} if edited else {}),
    }


def state(round_no: int) -> dict[str, Any]:
    """Threads, ranges and changes for round 1 or round 2."""
    names = SOURCE_NAMES_ROUND_1 if round_no == 1 else SOURCE_NAMES_ROUND_2
    # Keyed by the pathname each doc id is exported under in this round.
    text = {path: paper_text(path) for path in names.values()}
    main = text[names["doc-main"]]
    methods = text[names["doc-methods"]]
    results = text[names["doc-results"]]

    threads: dict[str, Any] = {
        "65a1f0a1b2c3d4e5f60718": {
            "messages": [
                _msg("m1", "Anchor intro: this reads like a promise. Say what is promised.", "Jasper Fuchs", "j.fuchs@example.edu", F1 + 4 * HOUR),
            ],
            "resolved": False,
        },
        "65a1f0a1b2c3d4e5f60719": {
            "messages": [
                _msg("m2", "Which grid? State the number of cells here.", "Jasper Fuchs", "j.fuchs@example.edu", F1 + 6 * HOUR),
                _msg("m3", "Agree, the count is doing a lot of work.", "Gregory Paradis", "g.paradis@example.ca", F1 + 9 * HOUR),
                _msg("m4", "Fine, and say which discount rates.", "Jasper Fuchs", "j.fuchs@example.edu", F1 + 26 * HOUR),
            ],
            "resolved": False,
        },
        "65a1f0a1b2c3d4e5f60720": {
            "messages": [
                _msg("m5", "Typo: 'allowence' should be 'allowance'.", "Jasper Fuchs", "j.fuchs@example.edu", F1 + 30 * HOUR),
                _msg("m6", "Fixed.", "Gregory Paradis", "g.paradis@example.ca", F1 + 31 * HOUR),
            ],
            "resolved": True,
            "resolved_at": F1 + 32 * HOUR,
            "resolved_by": {"id": "u-Jasper Fuchs", "name": "Jasper Fuchs", "email": "j.fuchs@example.edu"},
        },
        "65a1f0a1b2c3d4e5f60721": {
            # No range: Overleaf returns it, nothing in the source points at it.
            "messages": [_msg("m7", "General: thanks, reads much better overall.", "Jasper Fuchs", "j.fuchs@example.edu", F1 + 40 * HOUR)],
            "resolved": False,
        },
        "65a1f0a1b2c3d4e5f60724": {
            "messages": [_msg("m12", "Cut this clause; it restates the previous sentence.", "Jasper Fuchs", "j.fuchs@example.edu", F1 + 45 * HOUR)],
            "resolved": False,
        },
        "65a1f0a1b2c3d4e5f60722": {
            # The text it was written against has since been deleted, so the
            # exporter must report this one as a stale anchor.
            "messages": [_msg("m8", "I deleted the sentence I was asking about; keep the point though.", "Jasper Fuchs", "j.fuchs@example.edu", F1 + 44 * HOUR)],
            "resolved": False,
        },
    }

    if round_no == 2:
        threads["65a1f0a1b2c3d4e5f60723"] = {
            "messages": [
                _msg("m9", "Conclusion: drop the second half, it repeats the discussion.", "Jasper Fuchs", "j.fuchs@example.edu", F1 + 70 * HOUR),
                _msg("m10", "Agreed, cutting it.", "Gregory Paradis", "g.paradis@example.ca", F1 + 71 * HOUR),
            ],
            "resolved": False,
        }
        threads["65a1f0a1b2c3d4e5f60719"]["messages"].append(
            _msg("m11", "And is the budget in real or nominal terms?", "Jasper Fuchs", "j.fuchs@example.edu", F1 + 72 * HOUR)
        )
        threads["65a1f0a1b2c3d4e5f60719"]["resolved"] = True
        threads["65a1f0a1b2c3d4e5f60719"]["resolved_at"] = F1 + 73 * HOUR
        threads["65a1f0a1b2c3d4e5f60719"]["resolved_by"] = {
            "id": "u-Jasper Fuchs", "name": "Jasper Fuchs", "email": "j.fuchs@example.edu",
        }
        threads["65a1f0a1b2c3d4e5f60720"]["messages"][0]["content"] = (
            "Typo: 'allowence' should be 'allowance' (and check the caption too)."
        )
        threads["65a1f0a1b2c3d4e5f60720"]["messages"][0]["edited_at"] = F1 + 74 * HOUR

    def anchor(doc: str, phrase: str) -> dict[str, Any]:
        idx = text[doc].find(phrase)
        if idx < 0:
            raise SystemExit(f"fixture bug: {phrase!r} not found in {doc}")
        return {"op": {"p": idx, "c": phrase, "t": None}}

    def ranges() -> dict[str, Any]:
        docs = [
            {
                "id": "doc-main",
                "ranges": {
                    "comments": [
                        {"op": {"p": main.find("decline more slowly than they rise"),
                                "c": "decline more slowly than they rise",
                                "t": "65a1f0a1b2c3d4e5f60718"}}
                    ],
                    "changes": [
                        {"op": {"p": main.find("\\maketitle") + 10, "c": " Synthetic Paper Used Only To Test The Review Import", "t": "65a1f0a1b2c3d4e5f60731", "d": "insertion"}},
                        {"op": {"p": main.find("\\maketitle") + 10, "c": "A Paper", "t": "65a1f0a1b2c3d4e5f60732", "d": "deletion"}},
                    ],
                },
            },
            {
                "id": "doc-methods",
                "ranges": {
                    "comments": [
                        {"op": {"p": methods.find("$"), "c": "$", "t": "65a1f0a1b2c3d4e5f60719"}},
                        {"op": {"p": methods.find("under the fixture grid"),
                                "c": "the discount factor cancels in the occurrence ratio",
                                "t": "65a1f0a1b2c3d4e5f60722"}},
                        {"op": {"p": methods.find("persistence rather than disappearance"),
                                "c": "persistence rather than disappearance",
                                "t": "65a1f0a1b2c3d4e5f60724"}},
                    ],
                    "changes": [],
                },
            },
            {
                "id": "doc-results",
                "ranges": {
                    "comments": [
                        {"op": {"p": results.find("rate-independent under constant rates"),
                                "c": "rate-independent under constant rates",
                                "t": "65a1f0a1b2c3d4e5f60720"}},
                    ],
                    "changes": [],
                },
            },
        ]
        return {"docs": docs}

    if round_no == 2:
        extra = state2_ranges(text, names)
        return threads, ranges(), extra

    return threads, ranges(), {}


def state2_ranges(text: dict[str, str], names: dict[str, str]) -> dict[str, Any]:
    """Round 2: a new thread on the conclusion, and an extra tracked change."""
    main = text[names["doc-main"]]
    return {
        "docs": [
            {
                "id": "doc-main",
                "ranges": {
                    "comments": [
                        {"op": {"p": main.find("Synthetic conclusion text."),
                                "c": "Synthetic conclusion text.",
                                "t": "65a1f0a1b2c3d4e5f60723"}},
                    ],
                    "changes": [
                        {"op": {"p": main.find("Synthetic conclusion text."),
                                "c": "Synthetic conclusion, shortened.",
                                "t": "65a1f0a1b2c3d4e5f60733", "d": "insertion"}},
                    ],
                },
            }
        ],
        "_merge_into_main": True,
    }


RESULTS_TEX_ROUND_2 = RESULTS_TEX.replace(
    "rate-independent under constant rates",
    "rate-independent under constant rates in the fixture grid",
)


def paper_text(name: str) -> str:
    """Text as a given document id sees it in round 1 or round 2.

    Round 1 shows the pre-rename file names, so the import has to notice that the
    exported pathnames do not exist in this repository.
    """
    if name in ("sections/methods.tex",):
        return METHODS_TEX
    if name in ("sections/results.tex",):
        return RESULTS_TEX
    if name in ("sections/3_methods.tex",):
        return METHODS_TEX
    if name in ("sections/4_results.tex",):
        return RESULTS_TEX_ROUND_2
    return MAIN_TEX


def write_paper(paper_dir: Path) -> None:
    for rel, content in PAPER.items():
        target = paper_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith(".pdf"):
            target.write_bytes(content.encode("utf-8"))
        else:
            target.write_text(content, encoding="utf-8")


class FakeClient:
    """The surface run_export touches. Never opens a socket."""

    def __init__(self, threads: dict[str, Any], ranges: dict[str, Any],
                 names: dict[str, str], base_url: str = "", **kwargs: Any) -> None:
        self.base_url = base_url
        self.cookie_name = kwargs.get("cookie_name")
        self._threads = threads
        self._ranges = ranges
        self._names = names

    def connect(self, browser: str | None = None, cookie_value: str | None = None) -> None:
        return None

    def get_threads(self, project_id: str) -> dict[str, Any]:
        return self._threads

    def get_resolved_thread_ids(self, project_id: str) -> list[str]:
        return [t for t, v in self._threads.items() if v.get("resolved")]

    def get_project_metadata(self, project_id: str) -> dict[str, Any]:
        return {
            "files": {"docs": [], "folders": []},
            "name": "Synthetic fixture paper (NOT the real manuscript)",
            "rootDocId": "doc-main",
            "raw_meta": {},
        }

    def flatten_files(self, files_root: Any, debug_logger: Any = None) -> list[dict[str, str]]:
        return [{"doc_id": doc, "pathname": name} for doc, name in self._names.items()]

    def get_project_ranges(self, project_id: str) -> dict[str, Any]:
        return self._ranges

    def download_doc_text(self, project_id: str, doc_id: str) -> str:
        return paper_text(self._names[doc_id])

    def download_project_zip(self, project_id: str) -> bytes | None:
        return None

    def download_compiled_pdf(self, project_id: str, doc_id: str | None) -> bytes | None:
        return None

    def should_cancel(self) -> bool:
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="Where to write the fixture export")
    ap.add_argument("--paper", required=True, help="Where to write the synthetic paper tree")
    ap.add_argument("--round", type=int, default=1, choices=(1, 2))
    ap.add_argument("--no-source", action="store_true", help="Mimic the browser extension: no source/")
    args = ap.parse_args(argv)

    try:
        from overleaf_comments_export import export as export_mod
    except ImportError:
        print(
            "overleaf_comments_export is not importable. Run this with the pinned "
            "venv:\n  review/tools/.venv/bin/python review/tools/make_fixture_export.py ...",
            file=sys.stderr,
        )
        return 1

    threads, ranges, _ = state(args.round)
    names = SOURCE_NAMES_ROUND_1 if args.round == 1 else SOURCE_NAMES_ROUND_2

    # Round 2's new thread and tracked change ride along on the main document, so
    # the ranges payload has to carry them without losing round 1's entries.
    if args.round == 2:
        main_extra = state2_ranges({n: paper_text(n) for n in names.values()}, names)
        for doc in main_extra["docs"]:
            for existing in ranges["docs"]:
                if existing["id"] == doc["id"]:
                    existing["ranges"]["comments"].extend(doc["ranges"]["comments"])
                    existing["ranges"]["changes"].extend(doc["ranges"]["changes"])

    out_dir = Path(args.out).expanduser()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    paper_dir = Path(args.paper).expanduser()
    paper_dir.mkdir(parents=True, exist_ok=True)
    write_paper(paper_dir)

    export_mod.OverleafClient = lambda *a, **kw: FakeClient(threads, ranges, names, *a, **kw)
    result = export_mod.run_export(
        project_url=PROJECT_URL,
        out_dir=out_dir,
        project_title="Synthetic fixture paper (NOT the real manuscript)",
        include_source=not args.no_source,
        write_since=True,
        progress=lambda msg: print(f"  {msg}", file=sys.stderr),
    )
    print(f"Wrote {result.markdown_path}")
    print(f"Wrote {result.json_path}")
    print(f"Paper written to {paper_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

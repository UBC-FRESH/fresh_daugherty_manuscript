# Manuscript expansion plan — fresh_daugherty_manuscript

Date: 2026-09-23. Status: IMPLEMENTED (2026-09-24) — the full revision pass is on `main`:
co-author J. Fuchs added (title page + declarations; department/ORCID TODOs
flagged in-line); E1–E4 extensions written into Methods (§3.5), Results (§4.1,
Table 2, Figs. 2–3), Discussion (§5.1–5.4), Conclusion; abstract/keywords/
introduction updated; supplement pointers precise (E5/P13.3). Remaining:
J. Fuchs review comments (triage per below), then CJFR length/format check.

This repo is the Overleaf-linked manuscript repo
(`ubc-fresh/fresh_daugherty_manuscript`). **All manuscript work happens on
`main` here** (Overleaf git sync; no feature branches). Modelling work lives
in `ubc-fresh/fresh-daugherty` on phase branches per that repo's AGENTS.md
workflow; the detailed modelling plan is `planning/v0.2.0-plan.md` there
(phases P9–P13, issues #48–#69). This document is the paper-side companion.

## Authorship and framing changes

- **New co-author: Jasper Fuchs (BOKU, Austria).** Title page to be updated
  (author block, affiliation); detailed review comments from JF expected
  later — treat the extension backbone below as fixed structure his comments
  refine, not redesign.
- **Scope**: the paper expands from a pure reproduction report to
  reproduction + methodological extensions. The core reproduction
  (thesis grid: 18 landbases × 4 constant discount rates × 6 flow policies,
  432 cells) and its narrative stay essentially intact; the extensions are
  added as a clearly delimited second half.

## Structure changes (section-level)

- **Introduction**: one added paragraph framing the extensions — four
  pre-registered-style variants, each asking the same question: does the
  change *mitigate or eliminate* dynamic inconsistency?
- **Methods**: new subsection "Extensions" with four blocks, mirroring the
  modelling phases:
  - E1 — time-varying discount-rate paths (linear-declining; constant-then-
    exponential-decay "inverse-j"), vs the thesis's constant rates.
  - E2 — max-harvest-cap even-flow search: cap `H_t <= cap` + bisection
    tightening to an even-flow pattern metric (trend slope, max relative
    fluctuation, coefficient of variation, with recorded thresholds);
    evenness scored on the realized replanned trajectory.
  - E3 — value-denominated flow constraints: the bounded-deviation link on
    undiscounted net revenue instead of volume.
  - E4 — rolling-mean NDY: floor on `H_{t+1}` set by the backwards-facing
    2- or 3-period mean, under both anchoring readings (within-plan vs
    realized-history windows).
- **Results**: core-grid results unchanged; new "Extensions" subsection per
  E1–E4 with occurrence/magnitude tables and objective-gap-diagnostic
  evidence, each reported against the matched core-grid control.
- **Discussion**:
  - Extend the discount-rate nuance: occurrence was rate-independent under
    constant rates (the factor cancels); E1 tests whether *time-varying*
    impatience changes that — and flags the Strotz-type preference-level
    inconsistency that declining-rate paths themselves introduce.
  - E2 frames the cap search as automated allowable-cut calibration and
    connects to the remedies discussion.
  - E3 reports the filler-channel test: under revenue NDY, negatively-valued
    CM-CE area can never relax the floor — persistence vs disappearance of
    inconsistency discriminates the operative mechanism (ties to the
    negatively-valued-basis analysis already in the modelling repo's
    planning notes).
  - E4 reports the constraint-shape vs anchoring-institution contrast.
  - Limitations: add the grid-multiplicity caveat (extension grids are
    additive; the core grid is the fixed control).
- **Data availability / supplement pointers (E5)**: replace the current
  whole-repo references with section-level pointers into the curated
  `supplementary/` tree in `fresh-daugherty` (modelling-repo phase P13,
  issues #52/#67–#69). Every quantitative claim gets a specific supplement
  target.

## Figures and tables (planned)

- E1: occurrence/magnitude vs discount-path family; example trajectories.
- E2: calibrated-cap summary; evenness-metric components; realized vs
  projected trajectories under the calibrated cap.
- E3: dual-denominator (volume + revenue) divergence tables; CM-CE
  filler-variable presence/absence evidence.
- E4: occurrence/magnitude by window length `k` and anchoring reading.
- Existing Fig. 1 (declining NDY) and Table 1 (core grid) unchanged.

## Workflow rules for this repo

- Work on `main`; commit small and push promptly (Overleaf sync both ways —
  pull before editing).
- All numbers in the manuscript must trace to tracked records in
  `fresh-daugherty` (`results/experiments/`); no hand-typed results.
- When JF's review comments arrive: triage into (a) manuscript edits here,
  (b) modelling-requests filed as issues in `fresh-daugherty`.
- Journal target remains CJFR; revisit length/figure limits once the
  extension results land (expansion may require trimming elsewhere).

## Sequencing

1. Modelling phases P9–P12 land (any order; default P9 first), each ending
   with a draft write-up transferred here.
2. P13 builds the supplement in `fresh-daugherty`; P13.3 then rewrites the
   pointers here.
3. Full manuscript revision pass integrating E1–E4 results + JF comments,
   then submission.

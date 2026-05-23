# Human Review Log

Per L-10, every entry in `eval/golden_dataset.json` carries
`{reviewed_by, reviewed_at, reviewer_notes}` attribution. This file tracks
who reviewed what and when, satisfying OPS-04 attribution.

## Reviewers

## X-commando (2026-05-23)

Entries reviewed: 1, 2, 3, 4

- **Entry 1 (striper):** happy-path striper recommendation; bundles the
  deferred Phase 3 Path A hand-grade (showcase trace
  `cdaa58b7e3d0207b8e15660a404df7c0`).
- **Entry 2 (fluke):** drift speed + bucktail jargon for Manasquan Inlet.
- **Entry 3 (bluefish):** wire-leader / fishfinder rig for surf chunking.
- **Entry 4 (weakfish):** Raritan Bay spring weakfish geo + bait.

## Pending hand-review

Entries 5-20 (Wave 2 deliverable, plan 05-03)

- 5-8: tautog (4 entries)
- 9-12: striper jargon-heavy (schoolies, bunker pod, etc.)
- 13-16: fluke (doormat, drift, bucktail jig)
- 17-20: bluefish + weakfish hybrid (mixed-species queries)

## Wave 2 hand-review — 2026-05-23

**Reviewer:** X-commando
**Scope:** Entries 5-20 (16 entries; entries 1-4 carried over from Phase 3 Path A unchanged)

**Process:** LLM drafted 16 candidate entries; iterative refinement focused the dataset on data-driven product framing (system aggregates live conditions + corpus reports, NOT generic tactical advice).

**Final mix:**
- 7 casual (basic NJ angler / visitor / beginner questions)
- 3 jargon_heavy (specific NJ locations + lexicon)
- 2 happy_path (tactic-specific with location given)
- 2 definition (NJ-shore context + corpus evidence of recent usage)
- 2 out_of_scope (regulatory + freshwater refusals)

**Key product positioning enforced in every expected_answer:**
Every recommendation cites specific NOAA station readings (with timestamps) + recent corpus reports (with dates/sources) + falls back to F-16 honest empty-state when corpus is too thin. No generic "dawn or dusk on a tide change" rules-of-thumb.

**Revisions from initial drafts:**
- Entry 6 ("What's the snafu rig?") — restored from comparative aggregation to definitional pattern: NJ-context definition + when it shines + corpus-grounded recent usage
- Entry 19 — SWAPPED from "What's biting in NJ right now?" (overlapped with #17) to definitional "What's a doormat fluke?"
- Entries 8, 10, 12, 14, 15, 16, 17, 19 — reshaped to describe SYSTEM behavior (live data + RAG citations + ML/rules score) instead of generic angler knowledge

**All 16 entries:** approved + attributed at 2026-05-23T18:30:00Z

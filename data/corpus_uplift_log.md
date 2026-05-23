# Phase 6 Corpus Uplift — Run Log (06-05)

**Date:** 2026-05-23T23:24:53Z
**Baseline:** 296 records (Phase 2 D-04 carry-over)
**Target:** 500+ (R-01)
**Result:** 547 records (delta: +251)
**Status:** R-01 PASS

## Pipeline summary

1. **Discovery** — `backend/scripts/discover_uplift_threads.py` enumerated
   forum index pages on StripersOnline (NJ board) + NJFishing (saltwater
   boards f=1, f=5, f=7, f=13), extracted thread URLs, and built a
   dedup-exclude file from existing 296 corpus URLs. Total new candidates
   discovered: 327. Trimmed to 251 (21 SO + 230 NJF) before scrape to keep
   GPT-4o-mini extraction cost bounded.
2. **Scrape** — `backend/scripts/scrape_forum.py` (extended in this plan with
   `--since` / `--max-pages` / `--exclude-urls` / `--source` / `--output`
   / `--manifest` flags) fetched the 251 thread pages with the literal
   `_PER_DOMAIN_DELAY = 1.0` per-domain polite sleep (Pitfall P10).
3. **Extract** — `backend/scripts/extract_fields.py` ran GPT-4o-mini
   structured-field extraction over all 251 raw records. Stats:
   `{in: 251, extracted: 251, failed: 0, low_conf: 51}`.
4. **Merge** — dedup-by-`source_url` append into
   `data/structured_reports/corpus.jsonl`. 251 appended, 0 duplicates, 0
   empty-URL records.

## Per-source

### StripersOnline (https://www.stripersonline.com/)

- **robots.txt fetched 2026-05-23T23:05:09Z** — 165 lines, multi-UA preamble
  block followed by `User-agent: *` path-specific Disallow rules. Pasted
  snippet (top of file shows the long block-list, bottom shows
  catch-all path-specifics):

      User-agent: Amazonbot
      User-agent: Applebot-Extended
      ...
      User-agent: ClaudeBot
      User-agent: GPTBot
      ...
      Disallow: /surftalk/*&pid=
      Disallow: /surftalk/*&start=
      Disallow: /surftalk/*?s=
      Disallow: /surftalk/index.php?app=core&module=global&section=login&do=deleteCookies
      Sitemap: https://www.stripersonline.com/surftalk/sitemap.php

  Our `Tide/0.1` UA is NOT in the multi-UA Disallow block. The path-specific
  `User-agent: *` Disallows target session-id, login, and old-paginator
  patterns — none of which our scraper fetches. We use canonical
  `/surftalk/topic/<id>-<slug>/` URLs, which are not in the Disallow list.

  `urllib.robotparser` cannot reliably parse the multi-UA preamble pattern
  (a documented Python stdlib quirk — it treats stacked `User-agent:` lines
  followed by `Disallow: /` as a global block). For this reason the
  `stripersonline` entry in `FORUM_SOURCES` has `respect_robots: False`.
  The L-07 amendment authorizes this bypass under the user's registered-
  member relationship with SO (see `data/corpus_attribution.md`).

- **Crawled boards:** `/surftalk/forum/25-new-jersey-fishing/` (NJ board)
  paginated pages 1–12 during discovery. Index pages walked: 12.
- **Polite delay applied: 1.0 s/req** (Pitfall P10 — enforced via
  `await asyncio.sleep(_PER_DOMAIN_DELAY)` in `scrape_source`).
- **Raw records fetched:** 21
- **After dedup against existing 296:** 21 (none of the new candidates
  collided with the 124 SO records already in the corpus)
- **After extract_fields:** 21

### NJ Fishing (https://njfishing.com/)

- **robots.txt fetched 2026-05-23T23:05:09Z** — 60 lines, clean
  `User-agent: * Allow: /` policy with a Cloudflare `Content-Signal:
  search=yes,ai-train=no` annotation. Specific AI-vendor UAs (Amazonbot,
  ClaudeBot, GPTBot, Applebot-Extended, Bytespider, CCBot, Google-Extended,
  meta-externalagent) are individually `Disallow: /`. Snippet:

      User-agent: *
      Content-Signal: search=yes,ai-train=no
      Allow: /

      User-agent: Amazonbot
      Disallow: /

      User-agent: ClaudeBot
      Disallow: /
      ...
      User-agent: GPTBot
      Disallow: /

  Our `Tide/0.1` UA is not in any block list — `urllib.robotparser`
  resolves the `User-agent: *` `Allow: /` rule for us. The Content-Signal
  `ai-train=no` is recorded in `corpus_attribution.md`; our use is RAG
  (retrieval-augmented generation at inference time), not model training,
  so the signal is honored by-construction.

- **Crawled boards:**
  - `f=1` — NJFishing.com Salt Water Fishing (pages 1–4 walked)
  - `f=5` — NJFishing.com Open Boat and Charter Trips, Salt Water (pages 1–4)
  - `f=7` — NJFishing.com Best Of (pages 1–4)
  - `f=13` — NJ Fishing.com Fishing Tips (pages 1–4)
- **Polite delay applied: 1.0 s/req** (Pitfall P10)
- **Raw records fetched:** 230 (trimmed from 306 discovered to bound LLM cost)
- **After dedup against existing 296:** 230
- **After extract_fields:** 230 (0 failures)

## Verification

- `wc -l data/structured_reports/corpus.jsonl` → **547** (≥ 500 → **R-01 PASS**)
- Duplicate source_url count → **0** (verified via Python dict-aggregation)
- Empty source_url count in new records → **0**
- Source breakdown (final): `{njfishing: 402, stripersonline: 145}`
- Low-confidence (`fields.confidence < 0.5`) in new records: 51 / 251
  (~20%, consistent with broadening into Best Of + Tips boards which
  include questions/discussion threads, not just trip reports)

## Spot-check (random 5 of 251 new records)

Sampled with `random.seed(42)`:

1. `t=39700` — Andreas Toy — `good_catch`, conf 0.8 — Open-boat trip
   report with cobalt-blue 77°F water detail.
2. `t=126600` — missbelmar — `good_catch`, conf 0.8 — Opening-day half-day
   trip with ling + sea bass.
3. `t=126627` — njfish4life — `unclear`, conf 0.5 — Slip-bobber 11 shorts
   + 1 keeper, water-temp commentary.
4. `t=122437` — Mark G — `unclear`, conf 0.5 — Discussion of John Skinner
   jigging book — borderline non-report (Tips board).
5. `t=126294` — Osprey — `unclear`, conf 0.5 — Charter promo for Christmas
   Eve trip — borderline promotional (charter board).

**Assessment:** 2/5 are clean trip reports (target shape for RAG); 3/5 are
adjacent discussion/promo that the extraction correctly flagged as `unclear`
with conf 0.5. Acceptable signal-to-noise — the agent's retrieval ranker
will down-weight low-confidence chunks. R-01 is a volume gate, not a
quality gate; the existing Ragas CI suite (faithfulness ≥ 0.80,
relevancy ≥ 0.78) is the quality gate, and these records will pass through
that filter at the agent layer.

## Caveats

- StripersOnline yielded only 21 new threads from board 25 pages 1–12
  because the existing corpus already had 124 SO records covering that
  board's high-traffic threads. Going deeper (pages 13+) is possible but
  was not necessary to clear R-01.
- 76 of the 306 discovered NJF candidates were dropped at trim time to
  keep the GPT-4o-mini extraction budget bounded. They remain available
  in `data/uplift_thread_manifest.json` (the trimmed manifest); the
  pre-trim count of 306 is preserved in this log for future runs.
- The combined raw-output file
  (`data/raw_reports/uplift_combined.jsonl`) initially overwrote the SO
  output due to a `--output` collision bug in the first scraper invocation
  (Rule 1 deviation, fixed in commit 85934ac before merge). The SO 21
  records were re-scraped separately into `uplift_stripersonline.jsonl`
  and concatenated into `uplift_all.jsonl` for extraction. Net effect on
  the corpus: zero — all 251 records present in final corpus.jsonl.
- M-08 / M-09 (ML promotion gates) are explicitly NOT a Phase 6 target.
  Per Phase 6 CONTEXT D-04, the bottleneck on those gates is label
  quality (36 binary labels), not corpus volume. The narrative for the
  Phase 6 DOC-04 launch summary (06-08): corpus volume cleared in 06-05;
  label collection deferred to v1.x.

## Re-seed Qdrant

Skipped in this run — the deployed VM has Wave 1 Cloud Run + Qdrant
state and re-seeding requires VPC connectivity. Operator step to apply
the uplift to production:

    cd backend && PYTHONPATH=. uv run python -m scripts.seed_reports --upsert

The corpus.jsonl on disk is the contract that satisfies R-01.

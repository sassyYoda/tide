# Corpus Attribution — L-07 Compliance

All RAG corpus sources are reproduced under the user's authorized-member
relationship with each forum. Attribution is preserved in each Qdrant record's
payload (`source_name`, `source_url`, `original_author_handle`, `scrape_date`)
and in the raw `data/structured_reports/corpus.jsonl` file.

## Sources (active as of Phase 6 uplift, 2026-05-23)

### StripersOnline (https://www.stripersonline.com/)

- **Authorization:** user is a registered member of StripersOnline; the L-07
  amendment confirms scraping is authorized for the Tide research-MVP under
  this membership relationship.
- **robots.txt posture:** SO's robots.txt has a multi-UA preamble that
  `urllib.robotparser` parses as `Disallow: /` for *every* UA — which
  contradicts the site's actual indexing posture (Google indexes their
  threads). The AI-bot-specific Disallow rules don't match our `Tide/0.1`
  UA. We respect the path-specific catch-all rules (`/surftalk/*?s=`,
  `/surftalk/*&start=`, login/admin URLs) by sticking to canonical
  `/surftalk/topic/<id>-<slug>/` URLs which the catch-all `User-agent: *`
  block permits explicitly. See `data/corpus_uplift_log.md` for the
  fetched-robots-snapshot. Polite delay 1.0 s/req enforced regardless
  (`_PER_DOMAIN_DELAY = 1.0` in `backend/scripts/scrape_forum.py`).
- **Coverage:** the New Jersey board (`/surftalk/forum/25-new-jersey-fishing/`)
  fishing-reports threads. Phase 2 ingested 124 records; Phase 6 uplift added
  more via deeper index pagination.
- **Records (post-Phase 6 uplift):** see `data/corpus_uplift_log.md` for the
  delta.

### NJFishing (https://njfishing.com/)

- **Authorization:** same L-07 amendment as StripersOnline; user is a
  registered member.
- **robots.txt posture:** `User-agent: * Allow: /` with a Cloudflare-managed
  `Content-Signal: search=yes, ai-train=no` annotation. Our use is RAG (real-
  time retrieval-augmented generation, not training corpus) — but we record
  the `ai-train=no` signal here for transparency. Specific AI-vendor bots
  (Amazonbot, ClaudeBot, GPTBot, etc.) are blocked; our `Tide/0.1`
  user-agent is not on the block list. Polite delay 1.0 s/req enforced.
- **Coverage:** vBulletin `showthread.php?t=NNN` threads from the saltwater
  boards:
  - `f=1` — NJFishing.com Salt Water Fishing
  - `f=5` — NJFishing.com Open Boat and Charter Trips (Salt Water)
  - `f=7` — NJFishing.com Best Of
  - `f=13` — NJ Fishing.com Fishing Tips
- **Records (post-Phase 6 uplift):** see `data/corpus_uplift_log.md`.

### SurfTalk (https://www.surftalk.com/)

- **Status:** parked domain (returns lander page). Defined in
  `FORUM_SOURCES` but produces zero records. No active scraping.

### Reddit, FishBrain, Facebook reports

- **Reddit:** deferred (Phase 2 D-06.1).
- **FishBrain:** opportunistic top-up via `scripts/scrape_fishbrain.py`
  (Phase 2 D-06).
- **Facebook:** transcription-only via `data/fb_transcriptions.csv` (Phase 2
  D-04 manual flow). No live scraping of FB.

## Per-record attribution stored in Qdrant payload

Every corpus record carries:

| Field                     | Type     | Notes                                         |
| ------------------------- | -------- | --------------------------------------------- |
| `source_name`             | string   | `njfishing` / `stripersonline` / `fishbrain`  |
| `source_url`              | string   | Canonical thread URL — primary dedup key      |
| `original_author_handle`  | string?  | Preserved verbatim; redacted only on request  |
| `scrape_date`             | datetime | UTC ISO-8601                                  |
| `post_date`               | date?    | Parsed from the post; `null` when unparseable |

## Removal protocol

If any source revokes authorization (revoked L-07 amendment, forum-mod
takedown request, GDPR/CCPA delete request from a named author):

1. Drop the corresponding records from `data/structured_reports/corpus.jsonl`
   (matched by `source_url` for full-source removal, or
   `original_author_handle` for per-author removal).
2. Re-seed the Qdrant collection from the truncated corpus:
   `uv run python backend/scripts/seed_reports.py --upsert`.
3. Append the removal date + scope to this file under a `## Removals` heading.

## L-07 amendment summary

The Tide research MVP is built by the user (a member of both StripersOnline
and NJFishing) for portfolio and research purposes. The L-07 amendment
clarifies that the user's authorized-member relationship covers programmatic
reproduction of *publicly visible* thread content into the RAG corpus,
provided that:

1. Polite-scraping discipline is observed (1 req/s, robots.txt respected for
   sources where the parser doesn't false-disallow the entire site).
2. Author handles are preserved in attribution (no anonymization).
3. A removal protocol exists (above).
4. Content is used for retrieval-augmented response generation, not for
   training a model.

This file is the canonical record of that posture.

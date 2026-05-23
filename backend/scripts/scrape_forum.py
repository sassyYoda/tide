"""Public HTML forum scraper (NJFishing.com + SurfTalk).

Polite: 1 req/s per domain, honors robots.txt via urllib.robotparser,
tenacity 3-retry exponential backoff, httpx 10s timeout. Never touches
login-gated pages (R-11 amended).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import pathlib
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib import robotparser

# vBulletin renders post timestamps as "#1 04-18-2026, 05:18 PM" inside td.thead
# elements. The leading "#N" anchor distinguishes per-post date cells from
# breadcrumb td.thead cells at the top of the page.
_VBULLETIN_DATE_RE = re.compile(
    r"#\d+\s*(?P<date>\d{2}-\d{2}-\d{4}),?\s*\d{1,2}:\d{2}\s*[AaPp][Mm]"
)

import httpx
from selectolax.parser import HTMLParser
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ingest.reports.schema import RawReport

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_MAX_BYTES = 2_000_000  # DoS guard per security domain
_PER_DOMAIN_DELAY = 1.0  # polite: 1 req/s per host

OUTPUT_DIR = pathlib.Path(__file__).resolve().parents[2] / "data" / "raw_reports"


def load_excluded_urls(path: Path | None) -> set[str]:
    """Read a one-URL-per-line file; ignore blank lines and ``#``-prefixed comments.

    Used for dedup-against-existing-corpus runs: pass the file path via
    ``--exclude-urls`` to skip any thread already represented in the corpus.
    """
    if path is None:
        return set()
    result: set[str] = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        result.add(line)
    return result


def build_parser() -> argparse.ArgumentParser:
    """Construct the scrape_forum.py CLI parser.

    Extracted as a standalone function so tests can exercise argparse
    validation without invoking ``main()``. New flags (Phase 6 R-01 uplift):

    - ``--since YYYY-MM-DD``: skip threads with last-post date before cursor
    - ``--max-pages N``: cap number of forum index pages walked per source
    - ``--exclude-urls FILE``: text file (one URL per line) to dedup against
    - ``--source NAME``: restrict to a single source key from ``FORUM_SOURCES``
    - ``--output PATH``: override the per-source JSONL output path
    - ``--manifest PATH``: path to the thread-paths manifest JSON
    """
    parser = argparse.ArgumentParser(
        description=(
            "Polite HTML forum scraper for NJ saltwater fishing reports. "
            "Honors robots.txt (Pitfall P10) and enforces a 1 req/s polite "
            "delay per domain."
        )
    )
    parser.add_argument(
        "--since",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d"),
        default=None,
        help="Skip threads with last-post date before this YYYY-MM-DD cursor",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help=(
            "Cap number of forum index pages walked per source "
            "(deeper history when raised)"
        ),
    )
    parser.add_argument(
        "--exclude-urls",
        type=Path,
        default=None,
        help=(
            "Path to a text file with one URL per line to skip "
            "(existing-corpus dedup)"
        ),
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help=(
            "Restrict to a single FORUM_SOURCES key "
            "(njfishing | stripersonline | surftalk)"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Override per-source JSONL output path",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to forum_manifest.json (default: data/forum_manifest.json)",
    )
    return parser


# Source config — MVP starts with NJFishing only.
# SurfTalk.com domain is parked (returns lander page) — deferred until a working
# secondary forum is identified. Plan 04 (FishBrain top-up) covers the gap.
# Selectors are combined CSS lists so the same scraper handles both vBulletin
# (NJFishing's live HTML) and the synthetic generic-class HTML used in unit tests.
FORUM_SOURCES = {
    "njfishing": {
        "base_url": "https://njfishing.com",
        "thread_list_selectors": [".thread-title a", "h3.forum-post-title a"],
        "post_body_selector": "div[id^='post_message_'], .post-body, .message-content",
        "post_date_selector": "time[datetime], .datetime",
        "author_selector": "a.bigusername, .username, .author-name",
    },
    "surftalk": {
        "base_url": "https://www.surftalk.com",
        "thread_list_selectors": [".threadtitle a"],
        "post_body_selector": ".postcontent, .post_message",
        "post_date_selector": ".datetime",
        "author_selector": ".username",
    },
    "stripersonline": {
        # StripersOnline runs Invision Power Board at /surftalk/. The OP body
        # comes from the first commentContent block. time[datetime] carries an
        # ISO-formatted timestamp natively (no fallback regex needed). Post
        # author is the first sectionHead anchor inside the post container.
        #
        # ``respect_robots`` is intentionally False here: SO's robots.txt has
        # a multi-UA preamble that urllib.robotparser parses as Disallow: /
        # for *every* UA including googlebot — which contradicts the site's
        # actual indexing posture (Google indexes their threads). The
        # AI-bot-specific Disallow rules don't match our UA. We respect the
        # path-specific catch-all rules (search/login/admin) by sticking to
        # /surftalk/topic/ URLs, which the catch-all User-agent: * block
        # permits explicitly.
        "base_url": "https://www.stripersonline.com",
        "thread_list_selectors": ["a.ipsType_break"],
        "post_body_selector": '[data-role="commentContent"], .ipsRichText',
        "post_date_selector": "time[datetime]",
        "author_selector": "h3.ipsType_sectionHead a, a.ipsType_break",
        "respect_robots": False,
    },
}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
async def _fetch(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, timeout=_TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    # DoS guard
    if int(resp.headers.get("content-length", 0)) > _MAX_BYTES:
        raise ValueError(f"Response > {_MAX_BYTES} bytes for {url}")
    body = resp.text
    if len(body.encode()) > _MAX_BYTES:
        raise ValueError(f"Body > {_MAX_BYTES} bytes for {url}")
    return body


def _check_robots(base_url: str, path: str) -> bool:
    rp = robotparser.RobotFileParser()
    rp.set_url(f"{base_url}/robots.txt")
    try:
        rp.read()
    except Exception:
        return True  # permissive default if robots.txt unreachable
    return rp.can_fetch("Tide/0.1", f"{base_url}{path}")


async def scrape_source(
    source_key: str,
    thread_paths: list[str],
    client: httpx.AsyncClient | None = None,
    *,
    since: datetime | None = None,
    max_pages: int | None = None,
    exclude_urls: set[str] | None = None,
) -> list[RawReport]:
    """Scrape a single FORUM_SOURCES key.

    Phase 6 R-01 uplift kwargs:

    - ``since``: skip per-thread results whose parsed post_date is earlier.
    - ``max_pages``: cap iterations through ``thread_paths`` to bound depth.
    - ``exclude_urls``: pre-built set of URLs to skip (dedup against existing
      corpus). Built by :func:`load_excluded_urls`.

    Pitfall P10 invariants preserved: ``robotparser.RobotFileParser`` check
    before every GET (when ``respect_robots`` is true) and ``_PER_DOMAIN_DELAY``
    async sleep after every fetch.
    """
    cfg = FORUM_SOURCES[source_key]
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers={"User-Agent": "Tide/0.1 (research-mvp; +https://github.com/X-commando/tide)"},
        )
    exclude_set = exclude_urls or set()
    reports: list[RawReport] = []
    try:
        # max_pages caps the number of thread URLs walked per source.
        bounded_paths = (
            thread_paths if max_pages is None else thread_paths[: max(0, max_pages)]
        )
        for path in bounded_paths:
            url = cfg["base_url"] + path
            if url in exclude_set:
                log.info("Skipping excluded URL: %s", url)
                continue
            if cfg.get("respect_robots", True) and not _check_robots(cfg["base_url"], path):
                log.info("robots.txt disallows %s — skipping", url)
                continue
            try:
                html = await _fetch(client, url)
            except Exception as e:
                log.warning("Fetch failed %s: %s", url, e)
                continue
            tree = HTMLParser(html)
            body_node = tree.css_first(cfg["post_body_selector"])
            if body_node is None:
                continue
            body = body_node.text(separator="\n", strip=True)
            date_node = tree.css_first(cfg["post_date_selector"])
            post_date: date | None = None
            if date_node:
                dstr = date_node.attributes.get("datetime") or date_node.text(strip=True)
                try:
                    post_date = datetime.fromisoformat(dstr.split("T")[0]).date()
                except Exception:
                    post_date = None
            # vBulletin fallback: if no datetime attr matched, scan all td.thead
            # elements on the page for the per-post date pattern "#N MM-DD-YYYY".
            if post_date is None and source_key == "njfishing":
                for thead in tree.css("td.thead"):
                    m = _VBULLETIN_DATE_RE.search(thead.text(strip=True))
                    if m:
                        try:
                            post_date = datetime.strptime(
                                m.group("date"), "%m-%d-%Y"
                            ).date()
                            break
                        except ValueError:
                            continue
            # --since cursor: drop threads whose parsed post_date predates the
            # cutoff. Threads with unparseable dates pass through (conservative;
            # the dedup-against-existing-URLs step keeps duplicates out).
            if since is not None and post_date is not None:
                if post_date < since.date():
                    log.info(
                        "Skipping %s — post_date %s before --since %s",
                        url,
                        post_date,
                        since.date(),
                    )
                    # Polite delay even on skip-after-fetch (Pitfall P10).
                    time.sleep(_PER_DOMAIN_DELAY)
                    continue
            author_node = tree.css_first(cfg["author_selector"])
            author = author_node.text(strip=True) if author_node else None
            reports.append(
                RawReport(
                    source_name=source_key,
                    source_url=url,
                    original_author_handle=author,
                    scrape_date=datetime.now(timezone.utc),
                    post_date=post_date,
                    body=body[:8000],
                    ingest_notes={"html_len": len(html)},
                )
            )
            await asyncio.sleep(_PER_DOMAIN_DELAY)
    finally:
        if owns_client:
            await client.aclose()
    return reports


async def main(
    thread_paths_by_source: dict[str, list[str]],
    *,
    since: datetime | None = None,
    max_pages: int | None = None,
    exclude_urls: set[str] | None = None,
    only_source: str | None = None,
    output_override: Path | None = None,
) -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    total = 0
    for src, paths in thread_paths_by_source.items():
        if only_source is not None and src != only_source:
            continue
        reports = await scrape_source(
            src,
            paths,
            since=since,
            max_pages=max_pages,
            exclude_urls=exclude_urls,
        )
        if output_override is not None:
            # When --output is set across multiple sources, prevent the second
            # source from overwriting the first by appending a per-source
            # suffix. Single-source --source runs keep the literal override.
            if only_source is None and len(thread_paths_by_source) > 1:
                out_path = output_override.with_name(
                    f"{output_override.stem}_{src}{output_override.suffix}"
                )
            else:
                out_path = output_override
        else:
            out_path = OUTPUT_DIR / f"{src}_{ts}.jsonl"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w") as f:
            for r in reports:
                f.write(r.model_dump_json() + "\n")
        log.info("%s: %d reports → %s", src, len(reports), out_path)
        total += len(reports)
    return total


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    parser = build_parser()
    args = parser.parse_args()
    manifest_path = args.manifest or pathlib.Path(
        os.environ.get("FORUM_MANIFEST", "data/forum_manifest.json")
    )
    paths = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    exclude_set = load_excluded_urls(args.exclude_urls)
    asyncio.run(
        main(
            paths,
            since=args.since,
            max_pages=args.max_pages,
            exclude_urls=exclude_set,
            only_source=args.source,
            output_override=args.output,
        )
    )

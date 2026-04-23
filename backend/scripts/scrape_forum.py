"""Public HTML forum scraper (NJFishing.com + SurfTalk).

Polite: 1 req/s per domain, honors robots.txt via urllib.robotparser,
tenacity 3-retry exponential backoff, httpx 10s timeout. Never touches
login-gated pages (R-11 amended).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
from datetime import date, datetime, timezone
from urllib import robotparser

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


# Source config — MVP starts with these two; FishBrain top-up in Plan 04.
FORUM_SOURCES = {
    "njfishing": {
        "base_url": "https://njfishing.com",
        "thread_list_selectors": [".thread-title a", "h3.forum-post-title a"],
        "post_body_selector": ".post-body, .message-content",
        "post_date_selector": "time[datetime]",
        "author_selector": ".username, .author-name",
    },
    "surftalk": {
        "base_url": "https://www.surftalk.com",
        "thread_list_selectors": [".threadtitle a"],
        "post_body_selector": ".postcontent, .post_message",
        "post_date_selector": ".datetime",
        "author_selector": ".username",
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
) -> list[RawReport]:
    cfg = FORUM_SOURCES[source_key]
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers={"User-Agent": "Tide/0.1 (research-mvp; +https://github.com/X-commando/tide)"},
        )
    reports: list[RawReport] = []
    try:
        for path in thread_paths:
            url = cfg["base_url"] + path
            if not _check_robots(cfg["base_url"], path):
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


async def main(thread_paths_by_source: dict[str, list[str]]) -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    total = 0
    for src, paths in thread_paths_by_source.items():
        reports = await scrape_source(src, paths)
        out_path = OUTPUT_DIR / f"{src}_{ts}.jsonl"
        with out_path.open("w") as f:
            for r in reports:
                f.write(r.model_dump_json() + "\n")
        log.info("%s: %d reports → %s", src, len(reports), out_path)
        total += len(reports)
    return total


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    # Example: populate thread_paths_by_source from a manifest file
    manifest = pathlib.Path(os.environ.get("FORUM_MANIFEST", "data/forum_manifest.json"))
    paths = json.loads(manifest.read_text()) if manifest.exists() else {}
    asyncio.run(main(paths))

"""FishBrain public-catch scraper (R-01 top-up, all 5 species per D-06.1).

Originally D-02 scoped this to thin species (tautog, weakfish). Widened
2026-04-23 per D-06.1 to cover all 5 MVP species after Reddit was deferred.

ToS-grey but public HTML. Respects robots.txt and explicit `_MAX_BYTES` cap.
If HTML structure changes and selectors all miss, source is dropped (A8).

NOTE: Reads `FISHBRAIN_USER_AGENT` directly from os.environ rather than
importing app.config — the latter would require DATABASE_URL/OPENAI_API_KEY
at import time, which makes unit tests unimportable in CI. Same pattern as
extract_fields._load_openai_key().
"""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
from datetime import date, datetime, timezone
from urllib import robotparser

import httpx
from selectolax.parser import HTMLParser
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ingest.reports.schema import RawReport

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_MAX_BYTES = 2_000_000  # DoS guard
_PER_DOMAIN_DELAY = 2.0  # FishBrain — be extra polite (2x the forum baseline)

TARGET_SPECIES = {
    "tautog": ["tautog", "blackfish"],
    "weakfish": ["weakfish", "sea-trout"],
    "striper": ["striped-bass"],
    "fluke": ["summer-flounder", "fluke"],
    "bluefish": ["bluefish"],
}

# FishBrain public catch search URL template (read-only, not login-gated)
BASE_URL = "https://fishbrain.com"
SEARCH_PATH = "/catches?species={slug}&location=new-jersey"
MAX_PER_SPECIES = 100

OUTPUT_DIR = pathlib.Path(__file__).resolve().parents[2] / "data" / "raw_reports"


def _user_agent() -> str:
    return os.environ.get(
        "FISHBRAIN_USER_AGENT",
        "Tide/0.1 (+research-mvp; +https://github.com/X-commando/tide)",
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
async def _fetch(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, timeout=_TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
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
    return rp.can_fetch(_user_agent().split()[0], f"{base_url}{path}")


def _parse_catch_page(html: str, page_url: str) -> RawReport | None:
    """Extract one catch report from a FishBrain catch detail page.

    Selectors (best-effort — FishBrain markup changes; if all miss, return None):
    - .catch-body or .catch-description or [data-testid="catch-description"]
    - time[datetime] or .catch-date
    - .user-name or [data-testid="catch-user-name"]
    """
    tree = HTMLParser(html)
    body_node = (
        tree.css_first(".catch-body")
        or tree.css_first(".catch-description")
        or tree.css_first('[data-testid="catch-description"]')
    )
    if body_node is None:
        return None
    body = body_node.text(separator="\n", strip=True)
    if not body:
        return None
    # date
    date_node = tree.css_first("time[datetime]") or tree.css_first(".catch-date")
    post_date: date | None = None
    if date_node:
        dstr = date_node.attributes.get("datetime") or date_node.text(strip=True)
        if dstr:
            try:
                post_date = datetime.fromisoformat(dstr.split("T")[0]).date()
            except Exception:
                post_date = None
    # author (displayed handle; per D-09 preserve — user decides redaction policy)
    author_node = tree.css_first(".user-name") or tree.css_first(
        '[data-testid="catch-user-name"]'
    )
    author = author_node.text(strip=True) if author_node else None
    # structured hints for extractor
    species_node = tree.css_first(".species-name") or tree.css_first(
        '[data-testid="catch-species"]'
    )
    species_hint = species_node.text(strip=True) if species_node else None
    bait_node = tree.css_first(".lure-name") or tree.css_first(
        '[data-testid="catch-lure"]'
    )
    bait_hint = bait_node.text(strip=True) if bait_node else None
    return RawReport(
        source_name="fishbrain",
        source_url=page_url,
        original_author_handle=author,
        scrape_date=datetime.now(timezone.utc),
        post_date=post_date,
        body=body[:8000],
        ingest_notes={"species_hint": species_hint, "bait_hint": bait_hint},
    )


async def scrape_species(
    species: str,
    client: httpx.AsyncClient | None = None,
    max_per_species: int = MAX_PER_SPECIES,
) -> list[RawReport]:
    slugs = TARGET_SPECIES.get(species, [])
    if not slugs:
        return []
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers={"User-Agent": _user_agent()},
        )
    reports: list[RawReport] = []
    try:
        for slug in slugs:
            search_path = SEARCH_PATH.format(slug=slug)
            search_url = BASE_URL + search_path
            if not _check_robots(BASE_URL, search_path):
                log.info("robots.txt disallows %s — skipping species slug", search_url)
                continue
            try:
                index_html = await _fetch(client, search_url)
            except Exception as e:
                log.warning(
                    "FishBrain search %s failed: %s — skipping species slug",
                    search_url,
                    e,
                )
                continue
            tree = HTMLParser(index_html)
            catch_links = [
                a.attributes.get("href")
                for a in tree.css('a[href^="/catches/"], a[href*="/catch/"]')
                if a.attributes.get("href")
            ]
            catch_links = list(dict.fromkeys(catch_links))[:max_per_species]
            log.info("FishBrain %s: %d catch links", slug, len(catch_links))
            for href in catch_links:
                url = href if href.startswith("http") else BASE_URL + href
                try:
                    html = await _fetch(client, url)
                    rec = _parse_catch_page(html, url)
                    if rec:
                        reports.append(rec)
                except Exception as e:
                    log.warning("FishBrain catch %s failed: %s", url, e)
                await asyncio.sleep(_PER_DOMAIN_DELAY)
                if len(reports) >= max_per_species:
                    break
            if len(reports) >= max_per_species:
                break
    finally:
        if owns_client:
            await client.aclose()
    return reports


async def main(species_list: list[str] | None = None) -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # D-06.1: widened from thin-species-only (tautog, weakfish) to all 5
    # after Reddit was deferred. Tog/weakfish remain high-priority for label
    # density; pelagics (striper, fluke, bluefish) backfill corpus volume.
    species_list = species_list or [
        "tautog",
        "weakfish",
        "striper",
        "fluke",
        "bluefish",
    ]
    total = 0
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    for species in species_list:
        reports = await scrape_species(species)
        out_path = OUTPUT_DIR / f"fishbrain_{species}_{ts}.jsonl"
        with out_path.open("w") as fout:
            for r in reports:
                fout.write(r.model_dump_json() + "\n")
        log.info("FishBrain %s: %d reports → %s", species, len(reports), out_path)
        total += len(reports)
    return total


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    asyncio.run(main())

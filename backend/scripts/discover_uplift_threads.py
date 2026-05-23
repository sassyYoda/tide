"""Phase 6 R-01 uplift — discover new thread URLs for the corpus uplift run.

Enumerates forum index pages on StripersOnline (NJ board, /surftalk/forum/25/)
and NJFishing (/forums/forumdisplay.php?f=N for relevant saltwater boards),
extracts thread URLs, and deduplicates against the existing corpus.

Output:
  data/uplift_thread_manifest.json — same shape as forum_manifest.json
  (dict[source_key, list[thread_path]])
  data/already_scraped_urls.txt — the exclude-URLs file passed to scrape_forum.py

Polite: 1 req/s between index page fetches, respects robots.txt for NJFishing.
StripersOnline robots-bypass is L-07-authorized (documented in
corpus_attribution.md).
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import sys
import time
from urllib import robotparser

import httpx

log = logging.getLogger(__name__)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
STRUCT_DIR = DATA_DIR / "structured_reports"

USER_AGENT = "Tide/0.1 (research-mvp; +https://github.com/X-commando/tide)"
TIMEOUT = httpx.Timeout(15.0, connect=5.0)
POLITE_DELAY = 1.0  # 1 req/s per host (Pitfall P10)

# StripersOnline NJ board (L-07 authorized — see corpus_attribution.md)
SO_BASE = "https://www.stripersonline.com"
SO_NJ_BOARD = "/surftalk/forum/25-new-jersey-fishing/page/{n}/"

# NJFishing saltwater boards
NJF_BASE = "https://njfishing.com"
NJF_BOARDS = {
    1: "Salt Water Fishing",
    5: "Open Boat and Charter Trips (Salt Water)",
    7: "Best Of",
    13: "Fishing Tips",
}
NJF_BOARD_URL = "/forums/forumdisplay.php?f={fid}&page={n}"


def _check_robots(base_url: str, path: str, ua: str = "Tide/0.1") -> bool:
    rp = robotparser.RobotFileParser()
    rp.set_url(f"{base_url}/robots.txt")
    try:
        rp.read()
    except Exception:
        return True
    return rp.can_fetch(ua, f"{base_url}{path}")


def _load_existing_corpus_urls() -> set[str]:
    urls: set[str] = set()
    corpus = STRUCT_DIR / "corpus.jsonl"
    if not corpus.exists():
        return urls
    with corpus.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw = rec.get("raw") or rec
            url = raw.get("source_url") or rec.get("source_url")
            if url:
                urls.add(url)
    return urls


def _enumerate_stripersonline_nj(
    client: httpx.Client, max_pages: int, exclude: set[str]
) -> list[str]:
    paths: list[str] = []
    seen_paths: set[str] = set()
    re_topic = re.compile(
        r'href="https://www\.stripersonline\.com(/surftalk/topic/\d+-[^"]+)"'
    )
    for n in range(1, max_pages + 1):
        page_path = SO_NJ_BOARD.format(n=n)
        url = SO_BASE + page_path
        log.info("SO index page %d: %s", n, url)
        try:
            resp = client.get(url, timeout=TIMEOUT, follow_redirects=True)
            resp.raise_for_status()
        except Exception as e:
            log.warning("SO index fetch failed %s: %s", url, e)
            time.sleep(POLITE_DELAY)
            continue
        for m in re_topic.findall(resp.text):
            # Strip trailing query strings/fragments (e.g. ?do=getNewComment)
            tpath = m.split("?")[0].split("#")[0]
            if not tpath.endswith("/"):
                tpath = tpath + "/"
            full_url = SO_BASE + tpath
            if full_url in exclude or tpath in seen_paths:
                continue
            seen_paths.add(tpath)
            paths.append(tpath)
        time.sleep(POLITE_DELAY)
    return paths


def _enumerate_njfishing(
    client: httpx.Client, board_id: int, max_pages: int, exclude: set[str]
) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    # vBulletin shows showthread.php?...t=NNN; we canonicalize to ?t=NNN form.
    re_thread = re.compile(r'href="showthread\.php\?[^"]*t=(\d+)')
    for n in range(1, max_pages + 1):
        page_path = NJF_BOARD_URL.format(fid=board_id, n=n)
        url = NJF_BASE + page_path
        if not _check_robots(NJF_BASE, page_path):
            log.info("NJF robots.txt disallows %s — stopping board %d", url, board_id)
            break
        log.info("NJF f=%d page %d", board_id, n)
        try:
            resp = client.get(url, timeout=TIMEOUT, follow_redirects=True)
            resp.raise_for_status()
        except Exception as e:
            log.warning("NJF index fetch failed %s: %s", url, e)
            time.sleep(POLITE_DELAY)
            continue
        text = resp.text
        for tid in re_thread.findall(text):
            tpath = f"/forums/showthread.php?t={tid}"
            full_url = NJF_BASE + tpath
            if full_url in exclude or tpath in seen:
                continue
            seen.add(tpath)
            paths.append(tpath)
        time.sleep(POLITE_DELAY)
    return paths


def main(
    so_max_pages: int = 12,
    njf_pages_per_board: int = 4,
    output_manifest: pathlib.Path | None = None,
) -> dict[str, list[str]]:
    exclude = _load_existing_corpus_urls()
    log.info("Existing corpus URLs: %d", len(exclude))

    manifest: dict[str, list[str]] = {}
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(headers=headers, follow_redirects=True) as client:
        so_paths = _enumerate_stripersonline_nj(client, so_max_pages, exclude)
        manifest["stripersonline"] = so_paths
        log.info("SO new thread paths discovered: %d", len(so_paths))

        njf_all: list[str] = []
        for fid in NJF_BOARDS:
            board_paths = _enumerate_njfishing(client, fid, njf_pages_per_board, exclude)
            log.info("NJF f=%d new thread paths: %d", fid, len(board_paths))
            njf_all.extend(board_paths)
        # Dedup across boards (a thread can appear in multiple boards)
        seen: set[str] = set()
        njf_unique: list[str] = []
        for p in njf_all:
            if p in seen:
                continue
            seen.add(p)
            njf_unique.append(p)
        manifest["njfishing"] = njf_unique
        log.info("NJF unique new thread paths: %d", len(njf_unique))

    if output_manifest is None:
        output_manifest = DATA_DIR / "uplift_thread_manifest.json"
    output_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("Wrote %s", output_manifest)

    # Also emit the exclude-urls file the scraper expects (one URL per line).
    excl_path = DATA_DIR / "already_scraped_urls.txt"
    excl_path.write_text(
        "# Auto-generated from data/structured_reports/corpus.jsonl source_urls\n"
        + "\n".join(sorted(exclude))
        + "\n",
        encoding="utf-8",
    )
    log.info("Wrote %s (%d URLs)", excl_path, len(exclude))

    total = sum(len(v) for v in manifest.values())
    log.info("Total new thread candidates: %d", total)
    return manifest


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    so_pages = int(os.environ.get("SO_MAX_PAGES", "12"))
    njf_pages = int(os.environ.get("NJF_PAGES_PER_BOARD", "4"))
    manifest = main(so_max_pages=so_pages, njf_pages_per_board=njf_pages)
    total = sum(len(v) for v in manifest.values())
    print(f"Total candidates: {total}")
    if total == 0:
        sys.exit(2)

"""Phase 6 R-01 — CLI flag tests for scrape_forum.py uplift extensions.

Preserves Pitfall P10 invariants (robotparser import + 1 req/s polite delay).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_robotparser_still_imported():
    """Pitfall P10 invariant — robotparser import must remain."""
    import inspect

    from scripts import scrape_forum

    src = inspect.getsource(scrape_forum)
    assert (
        "from urllib import robotparser" in src
        or "import urllib.robotparser" in src
    ), "Pitfall P10 — robotparser import must be present"


def test_per_domain_delay_constant_present_and_at_least_one_second():
    """Pitfall P10 invariant — 1 req/s polite delay minimum."""
    from scripts import scrape_forum

    assert hasattr(scrape_forum, "_PER_DOMAIN_DELAY")
    assert scrape_forum._PER_DOMAIN_DELAY >= 1.0, (
        "Pitfall P10 — 1 req/s polite delay minimum"
    )


def test_load_excluded_urls_handles_blanks_and_comments(tmp_path: Path):
    from scripts.scrape_forum import load_excluded_urls

    p = tmp_path / "excl.txt"
    p.write_text(
        "# header comment\n"
        "https://example.com/thread/1\n"
        "\n"
        "https://example.com/thread/2\n"
        "# trailing comment\n",
        encoding="utf-8",
    )
    urls = load_excluded_urls(p)
    assert urls == {
        "https://example.com/thread/1",
        "https://example.com/thread/2",
    }


def test_load_excluded_urls_none_returns_empty_set():
    from scripts.scrape_forum import load_excluded_urls

    assert load_excluded_urls(None) == set()


def test_cli_parser_accepts_since_flag():
    from scripts.scrape_forum import build_parser

    parser = build_parser()
    args = parser.parse_args(["--since", "2024-01-01"])
    assert args.since == datetime(2024, 1, 1)


def test_cli_parser_accepts_max_pages_flag():
    from scripts.scrape_forum import build_parser

    parser = build_parser()
    args = parser.parse_args(["--max-pages", "30"])
    assert args.max_pages == 30


def test_cli_parser_accepts_exclude_urls_flag(tmp_path: Path):
    from scripts.scrape_forum import build_parser

    parser = build_parser()
    args = parser.parse_args(["--exclude-urls", str(tmp_path / "excl.txt")])
    assert args.exclude_urls == tmp_path / "excl.txt"


def test_cli_parser_rejects_invalid_since():
    from scripts.scrape_forum import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--since", "not-a-date"])


def test_multi_source_output_override_appends_source_suffix(tmp_path: Path):
    """Rule 1 fix: --output across multiple sources must not have source #2
    overwrite source #1's file. The scraper appends a `_<source>` suffix to
    the override stem when more than one source is in the manifest and no
    --source filter is set.
    """
    import asyncio

    import respx
    from httpx import Response

    from scripts.scrape_forum import main as scrape_main

    # Use selectors that match BOTH njfishing (.post-body + .username) AND
    # stripersonline ([data-role="commentContent"] + h3.ipsType_sectionHead a).
    sample_html = """
    <html><body>
      <div class="post-body" data-role="commentContent">Test report body</div>
      <time datetime="2024-10-15T18:00:00"></time>
      <span class="username">tester</span>
      <h3 class="ipsType_sectionHead"><a>tester_so</a></h3>
    </body></html>
    """

    out = tmp_path / "uplift.jsonl"
    with respx.mock(assert_all_called=False) as router:
        router.get("https://njfishing.com/robots.txt").mock(
            return_value=Response(200, text="User-agent: *\nAllow: /")
        )
        router.get("https://njfishing.com/t/a").mock(
            return_value=Response(200, text=sample_html)
        )
        router.get("https://www.stripersonline.com/t/b").mock(
            return_value=Response(200, text=sample_html)
        )

        asyncio.run(
            scrape_main(
                {
                    "njfishing": ["/t/a"],
                    "stripersonline": ["/t/b"],
                },
                output_override=out,
            )
        )

    nj_file = out.with_name("uplift_njfishing.jsonl")
    so_file = out.with_name("uplift_stripersonline.jsonl")
    assert nj_file.exists(), "njfishing output file missing — multi-source suffix not applied"
    assert so_file.exists(), "stripersonline output file missing — multi-source suffix not applied"
    # Neither should be empty (both sources scraped one thread each)
    assert nj_file.read_text().strip(), "njfishing output is empty"
    assert so_file.read_text().strip(), "stripersonline output is empty"

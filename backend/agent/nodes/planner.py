"""Planner node — natural-language query → structured intent.

Behavior (CONTEXT D-04 + RESEARCH Q7):

1. Normalize species nicknames (blackfish→tautog, schoolie→striper, etc.)
   using ``jargon_lexicon.yaml`` as INLINE TEXT in the system prompt
   (not enum, per Pitfall 8). The YAML in this repo carries species
   nicknames as a flat list with inline comments naming the canonical
   species; this module both ingests the list (so future YAML
   restructuring lights up automatically) AND carries a curated
   alias→canonical mapping derived from the comments. The system prompt
   is rendered from the curated mapping; the flat list is preserved as
   a "vocabulary anchor" tail-section for the LLM.
2. Classify intent: ``fishing-recommendation`` OR ``out-of-scope``.
3. On out-of-scope, emit ``reject_reason`` ∈ ``{non_mvp_species,
   non_nj_geo, non_fishing}``.
4. Parse ``time_window_label`` ("Saturday morning") into ``(start, end)``
   datetimes using a small inline helper (no extra date-parser dep).

SEC-06: user query is sent ONLY in ``HumanMessage``. ``SystemMessage``
contains the agent persona + lexicon excerpt — no user-controlled text.

W-4: ``ChatOpenAI(timeout=1.5, max_retries=0)`` leaves headroom inside
the A-07 first-byte ≤ 2 s budget after network/serialization overhead.
"""
from __future__ import annotations

import logging
import os
import pathlib
import time
from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from agent.state import (
    TideAgentState,
)

log = logging.getLogger(__name__)

# ─── Curated alias → canonical map (MVP-5 only) ─────────────────────────
# Derived from the inline comments in
# backend/rag/benchmark/jargon_lexicon.yaml (species_nicknames section)
# plus the W-0 sea-trout fix recorded in 03-WAVE0-NOTES.md.
#
# Keys are LOWER-CASED; matching is case-insensitive. The Planner LLM is
# told to "apply this mapping" — the LLM itself does the actual
# normalization (we never touch the user's query string), so this map is
# rendered into the SystemMessage as inline text.
_ALIAS_TO_CANONICAL: dict[str, str] = {
    # Striped bass
    "linesider": "striper",
    "rockfish": "striper",
    "schoolie": "striper",
    "schoolies": "striper",
    "striper": "striper",
    "stripers": "striper",
    "striped bass": "striper",
    # Fluke (summer flounder)
    "doormat": "fluke",
    "doormat fluke": "fluke",
    "fluke": "fluke",
    "fluker": "fluke",
    "flukers": "fluke",
    # NOTE: "flounder" is intentionally NOT mapped — winter flounder is a
    # different species and out of MVP-5; the LLM should set
    # reject_reason=non_mvp_species when the user means winter flounder.
    # Bluefish
    "chopper": "bluefish",
    "choppers": "bluefish",
    "chopper blue": "bluefish",
    "cocktail blue": "bluefish",
    "cocktail blues": "bluefish",
    "blue": "bluefish",
    "blues": "bluefish",
    "bluefish": "bluefish",
    # Weakfish (sea trout / tide-runner / weakie / hardhead)
    "weakie": "weakfish",
    "weakies": "weakfish",
    "hardhead": "weakfish",
    "sea trout": "weakfish",
    "sea-trout": "weakfish",
    "seatrout": "weakfish",
    "tide-runner": "weakfish",
    "tide runner": "weakfish",
    "weakfish": "weakfish",
    # Tautog
    "tog": "tautog",
    "blackfish": "tautog",
    "whitelegger": "tautog",
    "white legger": "tautog",
    "tautog": "tautog",
}

# ─── Lexicon load at import (mirrors ml.model._maybe_load_at_import) ────

_LEXICON_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "rag" / "benchmark" / "jargon_lexicon.yaml"
)
_NICKNAMES_BLOCK: str = ""
_LEXICON_TERM_COUNT: int = 0


def _build_nicknames_block(lex: dict[str, Any]) -> tuple[str, int]:
    """Render species_nicknames + curated alias map for the SystemMessage.

    Returns ``(rendered_block, lexicon_term_count)``. The rendered block
    is the curated alias→canonical map (the LLM's actual normalization
    target); the lexicon list (if present) is appended as a vocabulary
    anchor so the LLM also recognises terms the curated map didn't reach
    (rare back-bay slang etc.) — the LLM is instructed to leave
    species_canonical=null for those cases rather than guess.
    """
    raw_block = lex.get("species_nicknames")
    yaml_terms: list[str] = []
    if isinstance(raw_block, list):
        yaml_terms = [str(t) for t in raw_block if isinstance(t, (str, int))]
    elif isinstance(raw_block, dict):
        # If a future YAML edit moves to {alias: canonical} shape, harvest it
        # AND merge into the curated map at runtime (curated wins on
        # collision so we always control MVP-5 mappings).
        for k, v in raw_block.items():
            if isinstance(v, str):
                yaml_terms.append(str(k))

    # Curated map → rendered as inline `alias → canonical` text.
    curated_lines: list[str] = []
    # Group by canonical for readability.
    by_canonical: dict[str, list[str]] = {}
    for alias, canonical in _ALIAS_TO_CANONICAL.items():
        by_canonical.setdefault(canonical, []).append(alias)
    for canonical in ("striper", "fluke", "bluefish", "weakfish", "tautog"):
        aliases = sorted(set(by_canonical.get(canonical, [])))
        if aliases:
            curated_lines.append(
                f"  {canonical}: {', '.join(aliases)}"
            )
    curated_text = "\n".join(curated_lines) if curated_lines else "(empty)"

    # Vocabulary anchor: the YAML list (deduped, lowercased).
    anchor_terms = sorted({t.lower() for t in yaml_terms}) if yaml_terms else []
    anchor_text = ", ".join(anchor_terms) if anchor_terms else "(empty)"

    rendered = (
        "Curated alias → canonical mapping (apply BEFORE intent classification):\n"
        f"{curated_text}\n"
        "\n"
        "Vocabulary anchor (terms the corpus uses; if user mentions one of "
        "these but the curated map does not include it, set "
        "species_canonical=null and decide reject_reason from the rest of "
        "the query — do NOT guess a canonical):\n"
        f"  {anchor_text}"
    )
    return rendered, len(anchor_terms)


def _maybe_load_lexicon_at_import() -> None:
    global _NICKNAMES_BLOCK, _LEXICON_TERM_COUNT
    if os.environ.get("TIDE_LAZY_LEXICON_LOAD") == "1":
        return
    try:
        if _LEXICON_PATH.exists():
            data = yaml.safe_load(_LEXICON_PATH.read_text())
            block, count = _build_nicknames_block(data or {})
            _NICKNAMES_BLOCK = block
            _LEXICON_TERM_COUNT = count
            log.info(
                "planner: loaded nickname lexicon (anchor terms=%d, curated aliases=%d)",
                count, len(_ALIAS_TO_CANONICAL),
            )
        else:
            log.warning("planner: lexicon not found at %s", _LEXICON_PATH)
            # Even without the YAML on disk, the curated map is enough.
            _NICKNAMES_BLOCK, _LEXICON_TERM_COUNT = _build_nicknames_block({})
    except Exception as e:
        log.warning("planner: lexicon load deferred: %s", e)
        _NICKNAMES_BLOCK, _LEXICON_TERM_COUNT = _build_nicknames_block({})


_maybe_load_lexicon_at_import()


# ─── Pydantic structured-output schema ──────────────────────────────────


MVP5 = Literal["striper", "fluke", "bluefish", "weakfish", "tautog"]


class PlannerOutput(BaseModel):
    intent: Literal[
        "fishing-recommendation",
        "comparison",
        "best-of-all",
        "best-of-week",
        "definition",
        "out-of-scope",
    ]
    species_canonical: MVP5 | None = Field(
        default=None,
        description=(
            "One of striper/fluke/bluefish/weakfish/tautog after applying the "
            "nickname lexicon. Null if user mentioned no species or a "
            "non-MVP-5 species."
        ),
    )
    location_hint_raw: str | None = Field(
        default=None,
        max_length=120,  # MR (Phase 3 code-review): bound LLM output before it flows into cache hash
        description=(
            "Verbatim location string the user gave (e.g. 'Barnegat Inlet', "
            "'IBSP', 'north jetty'). Null if no location mentioned. "
            "Bounded to 120 chars."
        ),
    )
    compare_locations_raw: list[str] | None = Field(
        default=None,
        max_length=5,
        description=(
            "When intent='comparison', the verbatim location strings the user "
            "wants compared (e.g. ['Manasquan', 'Sandy Hook']). Each entry "
            "bounded to 60 chars. Null for non-comparison intents."
        ),
    )
    time_window_label: str | None = Field(
        default=None,
        max_length=80,  # MR: bound LLM output before it flows into cache hash
        description=(
            "Human time phrase like 'Saturday morning', 'this evening', "
            "'tomorrow afternoon'. Null if user did not specify. "
            "Bounded to 80 chars."
        ),
    )
    reject_reason: Literal["non_mvp_species", "non_nj_geo", "non_fishing", "none"] = "none"


# ─── LLM singleton ──────────────────────────────────────────────────────


_planner_llm: Any = None


def _get_planner_llm() -> Any:
    """Lazy-init so unit tests using ``stub_planner_llm`` fixture work.

    The fixture monkeypatches ``langchain_openai.ChatOpenAI`` to a stub
    BEFORE the test calls into ``planner_node`` — at first call we then
    instantiate the (now-stubbed) class.
    """
    global _planner_llm
    if _planner_llm is None:
        # W-4 stream-open progress(planner) emit (in route) takes the first-byte
        # constraint off the LLM. p95 end-to-end budget is 8s; 5s for the planner
        # LLM call leaves 3s for the rest of the graph + Synthesizer. (Phase 3
        # closeout adjustment — original 1.5s was too tight on cold-start
        # GPT-4o-mini structured-output with the lexicon-inline system prompt;
        # warm calls return in <1s but cold calls can take 2-4s.)
        base = ChatOpenAI(model="gpt-4o-mini", timeout=5.0, max_retries=1)
        _planner_llm = base.with_structured_output(PlannerOutput)
    return _planner_llm


def _reset_planner_llm_for_tests() -> None:
    """Test hook — call between tests that swap ``ChatOpenAI`` to refresh the singleton."""
    global _planner_llm
    _planner_llm = None


# ─── System prompt (lexicon inlined, NOT user-controlled) ───────────────


def _system_prompt() -> str:
    return (
        "You are the Planner for Tide, a NJ saltwater fishing recommender for "
        "the Barnegat Bay area. Parse the user's natural-language fishing query "
        "into a structured intent.\n"
        "\n"
        "MVP-5 species (the only species we cover): striper, fluke, bluefish, "
        "weakfish, tautog.\n"
        "\n"
        f"{_NICKNAMES_BLOCK}\n"
        "\n"
        "Intent values:\n"
        "- fishing-recommendation: a single-spot or anywhere-near-me question "
        "  ('stripers at manasquan saturday', 'how's the fluke bite').\n"
        "- comparison: user explicitly weighs ≥2 locations against each other "
        "  ('manasquan or sandy hook for striper', 'IBSP vs Barnegat for "
        "  fluke this weekend'). Extract every location verbatim into "
        "  compare_locations_raw. location_hint_raw stays null.\n"
        "- best-of-all: user asks for the BEST spot for a species without "
        "  specifying any location ('where should I fish for striped bass?', "
        "  'best spot for tautog tomorrow'). This is a WHERE question at "
        "  roughly-now. location_hint_raw stays null; species_canonical MUST "
        "  be set.\n"
        "- best-of-week: user asks WHEN (what day and/or time) to fish over a "
        "  multi-day FUTURE span without naming one specific day ('when should "
        "  I fish for striper this week', 'best day and time in the coming "
        "  week', 'what's the optimal window over the next few days', 'when "
        "  and where has the most optimal conditions this week'). The key "
        "  signal is choosing a future day/time across a span (we sweep our "
        "  7-day forecast). Distinguish from best-of-all, which is WHERE at "
        "  roughly-now. species_canonical SHOULD be set; location_hint_raw "
        "  stays null (we always sweep all candidate spots for the species — "
        "  ignore any named location for best-of-week).\n"
        "- definition: user asks WHAT a fishing term/technique/rig/bait/gear is "
        "  or how to use it ('what's the snafu rig', 'how do you fish a "
        "  bucktail', 'tell me about chunking bunker', 'what's chumming'). "
        "  Always classify gear/technique/rig/jargon questions as 'definition', "
        "  NOT out-of-scope — they are fishing questions even without a "
        "  species or location. Set species_canonical=null unless the user "
        "  asked about the term in connection with a specific MVP-5 species.\n"
        "- out-of-scope: only when the query truly is not about fishing.\n"
        "\n"
        "Reject paths (set intent='out-of-scope' and reject_reason accordingly):\n"
        "- non_mvp_species: user asked about a fish that is NOT one of the "
        "MVP-5 even after lexicon normalization (e.g., 'red drum', 'tuna', "
        "'flounder' meaning winter flounder, 'sea bass', 'porgy').\n"
        "- non_nj_geo: user asked about a location outside NJ saltwater (e.g., "
        "'Maine', 'Florida', 'Cape Cod', a freshwater 'lake' or 'pond', a "
        "'river' upstream of tidewater).\n"
        "- non_fishing: user asked something genuinely unrelated to fishing "
        "(e.g., 'rent a boat', 'swim', 'beach weather forecast', "
        "'restaurant'). Gear/technique/rig/jargon questions are NEVER "
        "non_fishing — they belong in 'definition'.\n"
        "\n"
        "When intent='fishing-recommendation', extract the verbatim location "
        "string (no normalization here — the Data Fetcher resolves spot names "
        "later) and the human time phrase exactly as the user wrote it.\n"
        "\n"
        "Do NOT invent species or locations the user did not mention. When "
        "the user did not specify a species, set species_canonical=null. When "
        "the user did not specify a location, set location_hint_raw=null."
    )


# ─── Time-window parser (small inline helper, no extra dep) ─────────────


_NJ = ZoneInfo("America/New_York")
_PERIOD_HOURS: dict[str, tuple[int, int]] = {
    "dawn": (5, 7),
    "morning": (6, 11),
    "afternoon": (12, 16),
    "evening": (17, 21),
    "dusk": (18, 20),
    "night": (21, 24),
}
_DAY_NAMES = [
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
]


def _parse_time_window(
    label: str | None, now: datetime | None = None,
) -> tuple[datetime | None, datetime | None]:
    """Best-effort parse of phrases like 'Saturday morning', 'tomorrow afternoon', 'this evening'.

    Returns ``(None, None)`` if unparseable. Conservative — wider Phase 5
    will use a real NLU. For Phase 3, a default 4-ish-hour window centered
    at the named period is sufficient for the Data Fetcher conditions read.
    """
    if not label:
        return (None, None)
    s = label.lower()
    n = (now or datetime.now(_NJ)).astimezone(_NJ)

    target_day = n.date()
    if "tomorrow" in s:
        target_day = target_day + timedelta(days=1)
    elif "tonight" in s:
        target_day = n.date()  # today
    else:
        for i, d in enumerate(_DAY_NAMES):
            if d in s:
                today_idx = n.weekday()
                delta = (i - today_idx) % 7
                # Default to NEXT occurrence (today only counts if "this" present)
                if delta == 0 and "this" not in s:
                    delta = 7
                target_day = (n + timedelta(days=delta)).date()
                break

    # Period token (default morning if nothing matches)
    start_hr, end_hr = (6, 11)
    matched_period = False
    for token, (a, b) in _PERIOD_HOURS.items():
        if token in s:
            start_hr, end_hr = a, b
            matched_period = True
            break

    if "tonight" in s and not matched_period:
        start_hr, end_hr = 17, 22

    start = datetime(
        target_day.year, target_day.month, target_day.day,
        start_hr, 0, tzinfo=_NJ,
    )
    if end_hr >= 24:
        end = datetime(
            target_day.year, target_day.month, target_day.day,
            23, 59, tzinfo=_NJ,
        )
    else:
        end = datetime(
            target_day.year, target_day.month, target_day.day,
            end_hr, 0, tzinfo=_NJ,
        )
    return (start, end)


# ─── Node ───────────────────────────────────────────────────────────────


async def planner_node(state: TideAgentState) -> dict[str, Any]:
    """Parse query → ``PlannerOutput`` → state-update dict.

    SEC-06: user content goes ONLY in ``HumanMessage``. The system prompt
    is constant and lexicon-derived; nothing user-controlled reaches it.
    """
    query = state.get("query", "")
    if not query:
        log.warning("planner_node: empty query")
        return {
            "intent": "out-of-scope",
            "reject_reason": "non_fishing",
            "planner_latency_ms": 0.0,
        }

    sys = SystemMessage(content=_system_prompt())
    user = HumanMessage(content=query)  # SEC-06: user content ONLY here

    t0 = time.perf_counter()
    llm = _get_planner_llm()
    out: PlannerOutput = await llm.ainvoke([sys, user])
    elapsed_ms = (time.perf_counter() - t0) * 1000

    # Defensive: structured-output guarantees a PlannerOutput, but stub
    # fixtures may return an unexpected shape — keep the contract crisp.
    if not isinstance(out, PlannerOutput):
        log.warning("planner_node: LLM returned %r — coercing to safe default", type(out))
        return {
            "intent": "out-of-scope",
            "reject_reason": "non_fishing",
            "planner_latency_ms": elapsed_ms,
        }

    start, end = _parse_time_window(out.time_window_label)

    # Defense-in-depth: trim/normalize compare_locations_raw before it flows
    # downstream. The planner schema bounds list length to 5 + each entry to
    # the model's natural string length; we additionally cap each entry to
    # 60 chars and drop blanks.
    compare_locs: list[str] | None = None
    if out.compare_locations_raw:
        compare_locs = [
            s.strip()[:60] for s in out.compare_locations_raw if s and s.strip()
        ] or None

    update: dict[str, Any] = {
        "intent": out.intent,
        "species_canonical": out.species_canonical,
        "location_hint_raw": out.location_hint_raw,
        "compare_locations_raw": compare_locs,
        "time_window_label": out.time_window_label,
        "time_window_start": start,
        "time_window_end": end,
        "reject_reason": out.reject_reason,
        "planner_latency_ms": elapsed_ms,
    }
    return update


__all__ = [
    "PlannerOutput",
    "planner_node",
    "_system_prompt",
    "_parse_time_window",
    "_NICKNAMES_BLOCK",
    "_LEXICON_TERM_COUNT",
    "_ALIAS_TO_CANONICAL",
    "_reset_planner_llm_for_tests",
]

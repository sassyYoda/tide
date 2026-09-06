"""Typed loader for config/species.json (M-02)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypedDict


# species_config.py at backend/ml/species_config.py
# parents[0]=ml, parents[1]=backend, parents[2]=repo_root
#
# The canonical file lives at backend/config/species.json so it is INSIDE the
# Docker build context (both Dockerfiles build from backend/). The repo-root
# config/species.json is a symlink kept for humans and docs. Resolution order:
#   1. TIDE_SPECIES_CONFIG_PATH env override
#   2. backend/config/species.json   (what the container ships)
#   3. <repo-root>/config/species.json (legacy location)
# The old parents[2]-only lookup resolved to /config/species.json inside the
# container, which does not exist — that silently disabled the whole ML
# subsystem in prod (healthz model flag, data_fetcher scoring, scorer task).
_CANDIDATES: tuple[Path, ...] = (
    Path(__file__).resolve().parents[1] / "config" / "species.json",
    Path(__file__).resolve().parents[2] / "config" / "species.json",
)


def _resolve_config_path() -> Path:
    override = os.environ.get("TIDE_SPECIES_CONFIG_PATH")
    if override:
        return Path(override)
    for candidate in _CANDIDATES:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "species.json not found; looked in: " + ", ".join(str(c) for c in _CANDIDATES)
    )


CONFIG_PATH = _resolve_config_path()

SPECIES_LIST: tuple[str, ...] = ("striper", "fluke", "bluefish", "weakfish", "tautog")


class SpeciesConfig(TypedDict):
    optimal_temp_range: list[float]  # [low, high] celsius
    preferred_tide_phase: str
    pressure_preference: str
    solunar_response: str
    primary_forage: list[str]
    time_of_day_bias: str


def load_species_config() -> dict[str, SpeciesConfig]:
    raw = json.loads(CONFIG_PATH.read_text())
    missing = set(SPECIES_LIST) - set(raw.keys())
    if missing:
        raise RuntimeError(f"config/species.json missing species: {missing}")
    return raw


# Import-time instantiation, fail-fast pattern from app/config.py
SPECIES_CONFIG: dict[str, SpeciesConfig] = load_species_config()

__all__ = ["SPECIES_LIST", "SPECIES_CONFIG", "SpeciesConfig", "load_species_config"]

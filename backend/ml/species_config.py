"""Typed loader for config/species.json (M-02)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict


# species_config.py at backend/ml/species_config.py
# parents[0]=ml, parents[1]=backend, parents[2]=repo_root
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "species.json"

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

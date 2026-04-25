"""M-02 — config/species.json has all 5 MVP species with required fields.

This is the one REAL (non-stub) test that lands in Wave 0 because
`config/species.json` is created in this same plan (Task 2). All other
Wave 0 test files are stubs that get implemented by Plans 01-07.
"""

from __future__ import annotations

import json
import pathlib

CONFIG_PATH = pathlib.Path(__file__).resolve().parents[3] / "config" / "species.json"
REQUIRED_SPECIES = {"striper", "fluke", "bluefish", "weakfish", "tautog"}
REQUIRED_FIELDS = {
    "optimal_temp_range",
    "preferred_tide_phase",
    "pressure_preference",
    "solunar_response",
    "primary_forage",
    "time_of_day_bias",
}


def test_all_five_species_present():
    data = json.loads(CONFIG_PATH.read_text())
    assert set(data.keys()) == REQUIRED_SPECIES


def test_every_species_has_required_fields():
    data = json.loads(CONFIG_PATH.read_text())
    for species, cfg in data.items():
        missing = REQUIRED_FIELDS - set(cfg.keys())
        assert not missing, f"{species} missing {missing}"


def test_tautog_d14_values():
    """D-14 tautog lock: temp 13-18C, tide slack, pressure dropping, solunar low, daytime bias."""
    data = json.loads(CONFIG_PATH.read_text())
    tog = data["tautog"]
    assert tog["optimal_temp_range"] == [13, 18]
    assert tog["preferred_tide_phase"] == "slack"
    assert tog["pressure_preference"] == "dropping"
    assert tog["solunar_response"] == "low"
    assert tog["time_of_day_bias"] == "daytime"
    assert "green_crab" in tog["primary_forage"]


def test_load_species_config_returns_all_five():
    from ml.species_config import load_species_config, SPECIES_LIST
    cfg = load_species_config()
    assert set(cfg.keys()) == set(SPECIES_LIST)


def test_load_species_config_tautog_d14_values():
    from ml.species_config import SPECIES_CONFIG
    tog = SPECIES_CONFIG["tautog"]
    assert tog["optimal_temp_range"] == [13, 18]
    assert tog["preferred_tide_phase"] == "slack"
    assert tog["solunar_response"] == "low"


def test_species_list_is_tuple_of_five():
    from ml.species_config import SPECIES_LIST
    assert len(SPECIES_LIST) == 5
    assert "tautog" in SPECIES_LIST

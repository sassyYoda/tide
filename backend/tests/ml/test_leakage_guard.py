"""M-14 + M-04 — temporal-holdout leakage assertion (PITFALLS.md §1).

This is a CRITICAL CI GATE. A failure here means a feature row for a TRAIN
label included source data at or after the TEST fold boundary — the model
would be able to predict the future.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_build_features_honors_t_minus_guard(async_session, migrated_ingest_db):
    """For a row at time T, the max source timestamp must be < T."""
    from db.models import WeatherObservation
    from ml.features import GUARD, build_features_for_rows

    station = "8534720"  # Phase 1 seeded NOAA station (Atlantic City)
    t = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Seed a weather observation at EXACTLY t — it must NOT appear in features.
    await async_session.merge(
        WeatherObservation(
            station_id=station,
            time=t,
            temperature_2m_c=20.0,
            surface_pressure_hpa=1013.0,
            wind_speed_ms=5.0,
            wind_dir_deg=180.0,
            precipitation_prob_pct=0.0,
            raw_payload={"test": "at_t"},
        )
    )
    # Seed one 30 min before t — this IS the eligible feature source.
    await async_session.merge(
        WeatherObservation(
            station_id=station,
            time=t - timedelta(minutes=30),
            temperature_2m_c=19.0,
            surface_pressure_hpa=1015.0,
            wind_speed_ms=4.0,
            wind_dir_deg=170.0,
            precipitation_prob_pct=0.0,
            raw_payload={"test": "30min_before"},
        )
    )
    await async_session.commit()

    spot_id = 1
    df = await build_features_for_rows(
        async_session,
        [(spot_id, t, "striper")],
        spot_type_by_id={spot_id: "jetty"},
        station_id_by_spot={spot_id: station},
    )
    assert len(df) == 1
    max_source = max(df.iloc[0]["_feature_source_times"])
    # Hard invariant per PITFALLS.md §1
    assert max_source < t, f"LEAKAGE: max source time {max_source} >= T {t}"
    assert max_source <= t - GUARD


@pytest.mark.asyncio
async def test_no_test_timestamps_in_training_features(
    async_session, migrated_ingest_db
):
    """Scan every training feature row — no source timestamp may be >= min(test.time).

    Uses synthetic labels + real DB-seeded environmental rows to catch any
    off-by-one in the feature builder.
    """
    from db.models import TidalObservation, WeatherObservation
    from ml.features import build_features_for_rows
    from ml.splits import temporal_split

    station = "8534720"
    base = datetime(2024, 10, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(20):
        ts = base + timedelta(days=i)
        await async_session.merge(
            WeatherObservation(
                station_id=station,
                time=ts - timedelta(hours=1),
                temperature_2m_c=20.0,
                surface_pressure_hpa=1013.0 + i,
                wind_speed_ms=5.0,
                wind_dir_deg=180.0,
                precipitation_prob_pct=0.0,
                raw_payload={"i": i},
            )
        )
        await async_session.merge(
            TidalObservation(
                station_id=station,
                time=ts - timedelta(hours=1),
                water_level_m=1.0 + i * 0.1,
                water_temp_c=15.0,
                raw_payload={"i": i},
            )
        )
    await async_session.commit()

    labels = pd.DataFrame(
        [
            {
                "spot_id": 1,
                "label_time": base + timedelta(days=i),
                "species": "striper",
                "y": i % 2,
            }
            for i in range(20)
        ]
    )
    train, _val, test = temporal_split(labels, train_frac=0.70, val_frac=0.15)
    test_min = test["label_time"].min()

    train_features = await build_features_for_rows(
        async_session,
        list(zip(train["spot_id"], train["label_time"], train["species"])),
        spot_type_by_id={1: "jetty"},
        station_id_by_spot={1: station},
    )
    for _, row in train_features.iterrows():
        for src_t in row["_feature_source_times"]:
            assert src_t < test_min, (
                f"LEAKAGE: training feature source time {src_t} >= test boundary {test_min}"
            )

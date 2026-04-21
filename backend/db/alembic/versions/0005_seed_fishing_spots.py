"""seed fishing_spots — idempotent data migration.

`fishing_spots` has a BIGSERIAL surrogate PK, so there is no natural column
to conflict on. This migration first installs a UNIQUE index on
`(name, lat, lon)` to act as the natural key, then upserts every row from
`seeds/fishing_spots.json` (curated in Plan 01-03) via ON CONFLICT DO UPDATE.

Unknown JSON keys (informational audit metadata preserved in the committed
JSON but not modeled as DB columns) are dropped via the `SPOT_COLUMNS`
whitelist — mitigates T-01-04-03.

FK `fishing_spots.nearest_station -> noaa_stations.station_id` is enforced
at INSERT time. Migration 0004 runs immediately before this one, so every
referenced station is already present.
"""
from __future__ import annotations

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0005_seed_fishing_spots"
down_revision = "0004_seed_noaa_stations"
branch_labels = None
depends_on = None

SEED_PATH = Path(__file__).resolve().parents[4] / "seeds" / "fishing_spots.json"

# Whitelist the columns the migration binds. Any extra JSON keys (audit
# rationale fields, source_url, etc.) are ignored and never reach the DB.
SPOT_COLUMNS = (
    "name",
    "lat",
    "lon",
    "water_body",
    "spot_type",
    "depth_ft",
    "species",
    "nearest_station",
    "orientation_deg",
    "access_type",
)


def upgrade() -> None:
    # Natural-key unique index enabling ON CONFLICT upsert idempotency.
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_fishing_spots_name_lat_lon
            ON fishing_spots (name, lat, lon);
            """
        )
    )

    with SEED_PATH.open() as f:
        rows = json.load(f)

    conn = op.get_bind()
    for r in rows:
        # Unknown keys dropped; missing keys bind to NULL.
        bind = {k: r.get(k) for k in SPOT_COLUMNS}
        conn.execute(
            sa.text(
                """
                INSERT INTO fishing_spots (
                    name, lat, lon, water_body, spot_type, depth_ft,
                    species, nearest_station, orientation_deg, access_type
                ) VALUES (
                    :name, :lat, :lon, :water_body, :spot_type, :depth_ft,
                    :species, :nearest_station, :orientation_deg, :access_type
                )
                ON CONFLICT (name, lat, lon) DO UPDATE SET
                    water_body       = EXCLUDED.water_body,
                    spot_type        = EXCLUDED.spot_type,
                    depth_ft         = EXCLUDED.depth_ft,
                    species          = EXCLUDED.species,
                    nearest_station  = EXCLUDED.nearest_station,
                    orientation_deg  = EXCLUDED.orientation_deg,
                    access_type      = EXCLUDED.access_type;
                """
            ),
            bind,
        )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS uq_fishing_spots_name_lat_lon;"))

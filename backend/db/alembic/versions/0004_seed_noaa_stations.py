"""seed noaa_stations — idempotent data migration.

Loads `seeds/noaa_stations.json` (curated in Plan 01-03) into the
`noaa_stations` master table. Safe to re-run: `ON CONFLICT (station_id) DO
UPDATE` upserts each row. Extra JSON keys (if any are added later without a
schema change) are silently ignored because the INSERT binds a fixed column
list.

Hardcoded seed path: `repo_root/seeds/noaa_stations.json`. The path is
resolved from this file's own location (no user-controlled path concat),
which mitigates T-01-04-01.
"""
from __future__ import annotations

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0004_seed_noaa_stations"
down_revision = "0003_cagg"
branch_labels = None
depends_on = None

# Path to seeds/noaa_stations.json.
# versions/0004_*.py -> db/alembic/versions (parents[0]=versions, parents[1]=alembic,
# parents[2]=db, parents[3]=backend, parents[4]=repo root)
SEED_PATH = Path(__file__).resolve().parents[4] / "seeds" / "noaa_stations.json"


def upgrade() -> None:
    with SEED_PATH.open() as f:
        rows = json.load(f)
    conn = op.get_bind()
    for r in rows:
        conn.execute(
            sa.text(
                """
                INSERT INTO noaa_stations (station_id, name, lat, lon, products, source_url)
                VALUES (:station_id, :name, :lat, :lon, :products, :source_url)
                ON CONFLICT (station_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    lat = EXCLUDED.lat,
                    lon = EXCLUDED.lon,
                    products = EXCLUDED.products,
                    source_url = EXCLUDED.source_url;
                """
            ),
            {
                "station_id": r["station_id"],
                "name": r["name"],
                "lat": r["lat"],
                "lon": r["lon"],
                "products": r["products"],  # TEXT[] — psycopg2 binds list -> pg array
                "source_url": r["source_url"],
            },
        )


def downgrade() -> None:
    # Data migration — safe to no-op. Dropping station rows would cascade FK
    # into fishing_spots; schema rollback is owned by 0001's downgrade.
    pass

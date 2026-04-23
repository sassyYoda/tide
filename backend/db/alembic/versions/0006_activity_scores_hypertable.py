"""0006 — activity_scores hypertable for per-spot × per-species XGBoost scores.

Hand-written raw SQL (autogenerate cannot express create_hypertable). The
table is append-only and partitioned by `time` with 1-day chunks — matching
the solunar_values cadence more closely than the 7-day observation chunks
because score writes are every-15-min for ~30 spots × 5 species = ~150 rows
per tick (14,400/day, ~432K/month — smaller than tidal_observations).

`raw_payload JSONB NOT NULL` carries the full feature vector + model_version
+ Optuna trial params per D-09 replayability. `shap_values JSONB NOT NULL`
carries the top-3 (feature_name, shap_value) pairs per M-10.

CHECK constraints enforce score ∈ [0,1] and confidence ∈ {high,moderate,low}
at the DB layer — catches bad inserts before Phase 3 agent reads them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_activity_scores"
down_revision = "0005_seed_fishing_spots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE activity_scores (
                spot_id        BIGINT      NOT NULL REFERENCES fishing_spots(spot_id),
                species        TEXT        NOT NULL,
                time           TIMESTAMPTZ NOT NULL,
                score          DOUBLE PRECISION NOT NULL CHECK (score >= 0 AND score <= 1),
                shap_values    JSONB       NOT NULL,
                model_version  TEXT        NOT NULL,
                confidence     TEXT        NOT NULL CHECK (confidence IN ('high','moderate','low')),
                is_forecast    BOOLEAN     NOT NULL DEFAULT FALSE,
                raw_payload    JSONB       NOT NULL,
                inserted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (spot_id, species, time)
            );
            """
        )
    )
    op.execute(
        sa.text(
            """
            SELECT create_hypertable(
                'activity_scores',
                by_range('time', INTERVAL '1 day'),
                if_not_exists => TRUE
            );
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS idx_activity_scores_spot_species_time_desc
                ON activity_scores (spot_id, species, time DESC);
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS activity_scores CASCADE;"))

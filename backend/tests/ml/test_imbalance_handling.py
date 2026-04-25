"""M-05 — scale_pos_weight is computed (not SMOTE)."""
from __future__ import annotations

import numpy as np
import pytest


def test_scale_pos_weight_formula():
    from ml.labels import compute_scale_pos_weight

    y = np.array([1, 1, 0, 0, 0, 0])  # 2 pos, 4 neg → spw = 2.0
    assert compute_scale_pos_weight(y) == 2.0


def test_scale_pos_weight_rejects_zero_positives():
    from ml.labels import compute_scale_pos_weight

    with pytest.raises(ValueError, match="zero positives"):
        compute_scale_pos_weight(np.array([0, 0, 0]))


def test_no_smote_import_anywhere_in_ml():
    """D-05 amendment: SMOTE is banned project-wide."""
    import pathlib
    import re

    repo_ml = pathlib.Path(__file__).resolve().parents[2] / "ml"
    for p in repo_ml.rglob("*.py"):
        body = p.read_text()
        assert not re.search(r"\bSMOTE\b", body), f"{p} mentions SMOTE — forbidden per D-05"
        assert "from imblearn" not in body, f"{p} imports imblearn — forbidden per D-05"

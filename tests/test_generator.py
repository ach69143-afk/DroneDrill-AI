"""Unit tests for DroneDrill AI Scenario Generator and Core Backend.

Tests:
1. 1000 practice scenarios contain zero held-out cells.
2. Same seed gives same scenario; repeated fingerprint is detected.
3. difficulty_index always within 0-1.
4. Cell coverage reporting and targeted cell generation.
"""

import random
from app.factors import (
    all_cells,
    HELD_OUT_CELLS,
    PRACTICE_CELLS,
)
from app.generator import (
    generate_scenario,
    generate_for_cell,
    coverage_report,
)
from app.db import (
    init_db,
    record_fingerprint,
    has_fingerprint,
    record_cell_seen,
)


def test_split_counts_and_partition():
    """Verify condition factors yield 1800 cells with an exact 80/20 split."""
    total_cells = all_cells()
    assert len(total_cells) == 1800
    assert len(HELD_OUT_CELLS) == 360  # 20%
    assert len(PRACTICE_CELLS) == 1440  # 80%
    assert len(HELD_OUT_CELLS.intersection(PRACTICE_CELLS)) == 0


def test_1000_practice_scenarios_contain_zero_held_out_cells():
    """Requirement: 1000 practice scenarios contain zero held-out cells."""
    rng = random.Random(2026)
    for _ in range(1000):
        scenario = generate_scenario(rng=rng, allow_held_out=False)
        cell = tuple(scenario["cell"])
        # Must never be in held-out
        assert cell not in HELD_OUT_CELLS, f"Found held-out cell in practice run: {cell}"
        # Must be in practice cells
        assert cell in PRACTICE_CELLS


def test_same_seed_gives_same_scenario_and_repeated_fingerprint(tmp_path):
    """Requirement: Same seed gives same scenario; repeated fingerprint is detected."""
    seed_value = 99991

    # Same seed yields completely identical scenario output
    scenario_a = generate_scenario(rng=random.Random(seed_value))
    scenario_b = generate_scenario(rng=random.Random(seed_value))

    assert scenario_a == scenario_b
    assert scenario_a["fingerprint"] == scenario_b["fingerprint"]
    assert scenario_a["scenario_id"] == scenario_b["scenario_id"]
    assert scenario_a["objects"] == scenario_b["objects"]

    # Test repeated fingerprint detection via DB
    test_db = str(tmp_path / "fingerprint_test.db")
    init_db(test_db)

    fp = scenario_a["fingerprint"]
    sc_id = scenario_a["scenario_id"]

    # First insertion succeeds (returns True)
    assert not has_fingerprint(fp, db_path=test_db)
    inserted_first = record_fingerprint(fp, sc_id, db_path=test_db)
    assert inserted_first is True

    # Repeated fingerprint is detected
    assert has_fingerprint(fp, db_path=test_db) is True
    inserted_second = record_fingerprint(fp, sc_id, db_path=test_db)
    assert inserted_second is False, "Repeated fingerprint was not detected/prevented"


def test_difficulty_index_always_within_0_to_1():
    """Requirement: difficulty_index always within 0-1."""
    rng = random.Random(42)
    for _ in range(500):
        scenario = generate_scenario(rng=rng, allow_held_out=True)
        diff = scenario["difficulty_index"]
        assert isinstance(diff, float)
        assert 0.0 <= diff <= 1.0, f"Difficulty index {diff} outside [0, 1] range"


def test_generate_for_cell():
    """Verify targeting a specific cell."""
    target_cell = list(PRACTICE_CELLS)[0]
    scenario = generate_for_cell(target_cell, rng=random.Random(101))
    assert tuple(scenario["cell"]) == target_cell
    assert 0.0 <= scenario["difficulty_index"] <= 1.0
    assert len(scenario["objects"]) >= 1


def test_coverage_report(tmp_path):
    """Verify coverage_report accurately calculates practice cells fraction."""
    test_db = str(tmp_path / "coverage_test.db")
    init_db(test_db)
    trainee_id = "trainee_unit_test"

    # Initial coverage is 0.0
    report_initial = coverage_report(trainee_id, db_path=test_db)
    assert report_initial == 0.0
    assert report_initial["seen"] == 0

    # Visit 10 distinct practice cells
    sample_cells = list(PRACTICE_CELLS)[:10]
    for cell in sample_cells:
        record_cell_seen(trainee_id, cell, db_path=test_db)

    report_after = coverage_report(trainee_id, db_path=test_db)
    expected_fraction = 10 / len(PRACTICE_CELLS)
    assert abs(report_after - expected_fraction) < 1e-6
    assert report_after["seen"] == 10
    assert report_after["total"] == len(PRACTICE_CELLS)

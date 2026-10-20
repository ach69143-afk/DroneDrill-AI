"""Unit tests for DroneDrill AI Adaptive Scenario Selector.

Tests:
1. 1000 selections never return a HELD_OUT cell.
2. For a trainee with one clearly weak condition, 60-80% of selections contain it.
"""

import random
from app.db import init_db, record_session
from app.factors import HELD_OUT_CELLS, PRACTICE_CELLS
from app.skill_model import update_from_result
from app.selector import select_next


def test_1000_selections_never_return_held_out_cell(tmp_path):
    """Requirement: 1000 selections never return a HELD_OUT cell."""
    db_file = str(tmp_path / "selector_test.db")
    init_db(db_file)
    trainee_id = "trainee_invariance"

    rng = random.Random(1001)
    for _ in range(1000):
        selection = select_next(trainee_id, rng=rng, db_path=db_file)
        scenario = selection["scenario"]
        cell_tuple = tuple(scenario["cell"])
        assert cell_tuple not in HELD_OUT_CELLS, f"Found held-out cell: {cell_tuple}"
        assert cell_tuple in PRACTICE_CELLS, f"Cell not in practice set: {cell_tuple}"


def test_weak_condition_targeted_60_to_80_percent(tmp_path):
    """Requirement: For a trainee with one clearly weak condition, 60-80% of selections contain it."""
    db_file = str(tmp_path / "selector_weak_test.db")
    init_db(db_file)
    trainee_id = "trainee_weak_fog"

    # Trainee has at least 3 practice sessions completed
    for i in range(3):
        record_session(
            session_id=f"sess_init_{i}",
            trainee_id=trainee_id,
            scenario_id=f"sc_init_{i}",
            cell=["day", "clear", "open", "EO", "none", "none"],
            difficulty_index=0.5,
            mode="practice",
            db_path=db_file,
        )

    # High performance across normal conditions
    for _ in range(5):
        update_from_result(
            trainee_id,
            {"classification|day/clear/open/EO/none/none": 0.85},
            db_path=db_file,
        )

    # Clearly weak condition specifically in fog (mean < 0.25 over 5 updates)
    for _ in range(5):
        update_from_result(
            trainee_id,
            {"classification|day/fog/open/EO/none/none": 0.10},
            db_path=db_file,
        )

    rng = random.Random(2026)
    num_trials = 600
    fog_count = 0

    for _ in range(num_trials):
        selection = select_next(trainee_id, rng=rng, db_path=db_file)
        scenario = selection["scenario"]
        # weather is factor index 1 in cell
        if scenario["cell"][1] == "fog":
            fog_count += 1

    fraction = fog_count / num_trials
    # Target probability is 0.70; requirement specifies 60-80%
    assert 0.60 <= fraction <= 0.80, f"Expected 60-80% weak condition targeting, got {fraction * 100:.1f}%"

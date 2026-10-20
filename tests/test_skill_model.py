"""Unit tests for DroneDrill AI Bayesian Skill Model.

Tests:
1. Good scores raise the posterior mean above 0.5.
2. Bad scores lower the posterior mean below 0.5.
3. weak_conditions respects min_evidence and threshold filters.
4. skill_matrix returns full hierarchy across all 5 skills and condition factors.
"""

from app.db import init_db
from app.factors import CONDITION_FACTOR_NAMES
from app.skill_model import (
    SKILLS,
    update_from_result,
    get_posterior,
    weak_conditions,
    skill_matrix,
)


def test_good_scores_raise_the_mean(tmp_path):
    """Requirement: Good scores raise the posterior mean."""
    db_file = str(tmp_path / "skill_test.db")
    init_db(db_file)
    trainee_id = "trainee_good_score"

    # Initial prior Beta(1, 1) has mean = 0.5, n = 0
    prior = get_posterior(trainee_id, "classification", "weather", "clear", db_path=db_file)
    assert prior["mean"] == 0.5
    assert prior["n"] == 0

    # Submit a high score (0.95) on clear weather
    update_from_result(
        trainee_id,
        {"classification|day/clear/open/EO/none/none": 0.95},
        db_path=db_file,
    )

    posterior = get_posterior(trainee_id, "classification", "weather", "clear", db_path=db_file)
    assert posterior["mean"] > 0.5
    assert posterior["n"] == 1
    # Expected alpha = 1.95, beta = 1.05 -> mean = 1.95 / 3 = 0.65
    assert abs(posterior["mean"] - 0.65) < 0.01


def test_bad_scores_lower_the_mean(tmp_path):
    """Requirement: Bad scores lower the posterior mean."""
    db_file = str(tmp_path / "skill_test.db")
    init_db(db_file)
    trainee_id = "trainee_bad_score"

    # Initial prior Beta(1, 1) has mean = 0.5
    prior = get_posterior(trainee_id, "classification", "weather", "fog", db_path=db_file)
    assert prior["mean"] == 0.5

    # Submit a low score (0.15) on fog
    update_from_result(
        trainee_id,
        {"classification|day/fog/open/EO/none/none": 0.15},
        db_path=db_file,
    )

    posterior = get_posterior(trainee_id, "classification", "weather", "fog", db_path=db_file)
    assert posterior["mean"] < 0.5
    assert posterior["n"] == 1
    # Expected alpha = 1.15, beta = 1.85 -> mean = 1.15 / 3 ≈ 0.3833
    assert abs(posterior["mean"] - 0.3833) < 0.01


def test_weak_conditions_respects_min_evidence(tmp_path):
    """Requirement: weak_conditions respects min_evidence."""
    db_file = str(tmp_path / "skill_test.db")
    init_db(db_file)
    trainee_id = "trainee_evidence"

    # Session 1 & 2: Bad scores (0.10) in fog
    for _ in range(2):
        update_from_result(
            trainee_id,
            {"classification|day/fog/open/EO/none/none": 0.10},
            db_path=db_file,
        )

    # With min_evidence = 3, n = 2 is not enough evidence yet
    weak_before = weak_conditions(trainee_id, min_evidence=3, threshold=0.6, db_path=db_file)
    assert ("classification", "weather", "fog") not in weak_before

    # Session 3: Third bad score in fog brings n = 3
    update_from_result(
        trainee_id,
        {"classification|day/fog/open/EO/none/none": 0.10},
        db_path=db_file,
    )

    weak_after = weak_conditions(trainee_id, min_evidence=3, threshold=0.6, db_path=db_file)
    assert ("classification", "weather", "fog") in weak_after


def test_skill_matrix_structure(tmp_path):
    """Verify skill_matrix returns full hierarchy with all 5 skills and factors."""
    db_file = str(tmp_path / "skill_test.db")
    init_db(db_file)
    matrix = skill_matrix("trainee_matrix_check", db_path=db_file)

    for skill in SKILLS:
        assert skill in matrix
        for factor in CONDITION_FACTOR_NAMES:
            assert factor in matrix[skill]
            for level, stats in matrix[skill][factor].items():
                assert "mean" in stats
                assert "sd" in stats
                assert "n" in stats

"""Unit tests for DroneDrill AI Generalization and Rote Metrics.

Tests:
1. Equal practice and test performance gives a Generalization Score close to 1.0.
2. A learner with a large rote_bonus gives a clearly positive rote gap.
"""

from app.db import init_db, record_session, update_session_score
from app.generalization import generalization_score, rote_indicator
from app.sim_learner import SimLearner
from app.generator import generate_scenario


def test_equal_practice_and_test_performance_gives_score_close_to_one(tmp_path):
    """Requirement: Equal practice and test performance gives a score close to 1.0."""
    db_file = str(tmp_path / "gen_score_test.db")
    init_db(db_file)
    trainee_id = "trainee_equal_perf"

    # 3 Practice sessions with 0.80 score at difficulty 0.50
    for i in range(3):
        sess_id = f"prac_{i}"
        record_session(
            session_id=sess_id,
            trainee_id=trainee_id,
            scenario_id=f"sc_prac_{i}",
            cell=["day", "clear", "open", "EO", "none", "none"],
            difficulty_index=0.50,
            mode="practice",
            db_path=db_file,
        )
        update_session_score(sess_id, 0.80, db_path=db_file)

    # 3 Test sessions with 0.80 score at matched difficulty 0.52
    for i in range(3):
        sess_id = f"test_{i}"
        record_session(
            session_id=sess_id,
            trainee_id=trainee_id,
            scenario_id=f"sc_test_{i}",
            cell=["night", "fog", "urban", "thermal", "noise", "birds"],
            difficulty_index=0.52,
            mode="test",
            db_path=db_file,
        )
        update_session_score(sess_id, 0.80, db_path=db_file)

    result = generalization_score(trainee_id, db_path=db_file)
    assert result["score"] is not None
    assert abs(result["score"] - 1.0) < 0.05, f"Expected generalization score ~1.0, got {result['score']}"


def test_learner_with_large_rote_bonus_gives_positive_rote_gap(tmp_path):
    """Requirement: A learner with a large rote_bonus gives a clearly positive rote gap."""
    db_file = str(tmp_path / "rote_gap_test.db")
    init_db(db_file)
    trainee_id = "trainee_rote_learner"

    # Synthetic learner with base skill 0.55 and a high rote bonus (+0.35)
    learner = SimLearner(base_skill=0.55, rote_bonus=0.35, rng=42)

    # 4 Novel practice sessions
    for i in range(4):
        sess_id = f"novel_{i}"
        sc = generate_scenario(rng=100 + i, allow_held_out=False)
        record_session(
            session_id=sess_id,
            trainee_id=trainee_id,
            scenario_id=sc["scenario_id"],
            cell=sc["cell"],
            difficulty_index=sc["difficulty_index"],
            mode="practice",
            is_repeat=0,
            fingerprint=sc["fingerprint"],
            db_path=db_file,
        )
        scores = learner.evaluate_scenario(sc, is_repeat=False)
        update_session_score(sess_id, scores["overall"], db_path=db_file)

    # 4 Repeated practice sessions (using the same scenarios with is_repeat=True)
    for i in range(4):
        sess_id = f"repeat_{i}"
        sc = generate_scenario(rng=100 + i, allow_held_out=False)
        record_session(
            session_id=sess_id,
            trainee_id=trainee_id,
            scenario_id=sc["scenario_id"],
            cell=sc["cell"],
            difficulty_index=sc["difficulty_index"],
            mode="practice",
            is_repeat=1,
            fingerprint=sc["fingerprint"],
            db_path=db_file,
        )
        scores = learner.evaluate_scenario(sc, is_repeat=True)
        update_session_score(sess_id, scores["overall"], db_path=db_file)

    indicator = rote_indicator(trainee_id, db_path=db_file)
    assert indicator["gap"] is not None
    # With a +0.35 rote bonus, the gap should be distinctly positive (> 0.10)
    assert indicator["gap"] > 0.10, f"Expected clearly positive rote gap (> 0.10), got {indicator['gap']}"

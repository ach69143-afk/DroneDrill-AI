"""Unit tests for DroneDrill AI Scoring Engine.

Requirements:
1. Perfect trainee gives overall > 0.8.
2. Trainee who misses everything gives detection_score near 0 and overall < 0.3.
3. d' for 8 hits of 10 and 1 false alarm of 10 noise windows matches a hand-computed value within 0.01.
4. Overconfident-wrong (confidence 0.95 on wrong class) gets lower calibration_score than hedged-wrong (0.5).
5. decision_tree.json loads and covers all 12 class|behaviour keys.
"""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.factors import CLASS_MIX, BEHAVIOUR_LABEL
from app.generator import generate_scenario
from app.scoring import score_session, load_decision_tree
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_decision_tree_covers_all_twelve_rules():
    """Requirement: decision_tree.json loads and covers all 12 class|behaviour keys."""
    tree = load_decision_tree()
    assert "_status" in tree
    assert "Instructor-editable draft" in tree["_status"]
    rules = tree.get("rules", {})

    expected_combinations = [f"{cls}|{beh}" for cls in CLASS_MIX for beh in BEHAVIOUR_LABEL]
    assert len(expected_combinations) == 12

    for key in expected_combinations:
        assert key in rules, f"Missing rule for key {key}"
        rule = rules[key]
        assert "expected_threat_level" in rule
        assert rule["expected_threat_level"] in (0, 1, 2, 3)
        assert "responses" in rule
        assert isinstance(rule["responses"], dict)
        assert len(rule["responses"]) > 0
        assert "countermeasure_simulated" in rule["responses"]

    assert "countermeasure_simulated" in tree.get("responses", [])
    assert rules["multirotor|suspicious"]["responses"]["countermeasure_simulated"] == 0.5
    assert rules["fixed_wing_uav|suspicious"]["responses"]["countermeasure_simulated"] == 0.5
    assert rules["unknown|suspicious"]["responses"]["countermeasure_simulated"] == 0.5
    assert rules["bird|benign"]["responses"]["countermeasure_simulated"] == 0.0


def test_d_prime_hand_computed_match():
    """Requirement: d' for 8 hits of 10 and 1 false alarm of 10 noise windows matches a hand-computed value within 0.01.
    
    Hand computation:
    hits = 8, n_obj = 10 -> hit_rate = (8 + 0.5) / (10 + 1) = 8.5 / 11 ≈ 0.772727
    fa = 1, noise_windows = 10 -> fa_rate = (1 + 0.5) / (10 + 1) = 1.5 / 11 ≈ 0.136364
    z(hit_rate) = norm.ppf(8.5/11) ≈ 0.747863
    z(fa_rate) = norm.ppf(1.5/11) ≈ -1.096894
    d' = z(hit_rate) - z(fa_rate) ≈ 1.844757 (≈ 1.845)
    """
    objects = [
        {
            "id": f"obj_{i+1}",
            "true_class": "multirotor",
            "true_threat_level": 2,
            "behaviour_label": "suspicious",
            "start_position": [0, 0, 0],
            "velocity": [0, 0, 0],
            "appears_at_time": 0.0,
        }
        for i in range(10)
    ]

    scenario = {
        "scenario_id": "test_sdt_scenario",
        "cell": ["day", "clear", "open", "EO", "none", "none"],
        "factors": {"distractors": "none"},
        "objects": objects,
        "duration_s": 60.0,
        "difficulty_index": 0.5,
        "noise_windows": 10,
        "fingerprint": "fake_fp",
    }

    # Trainee detects 8 out of 10 objects
    events = [
        {
            "object_id": f"obj_{i+1}",
            "detected": (i < 8),
            "detect_time_s": 5.0,
            "classified_as": "multirotor",
            "threat_level_rated": 2,
            "response_chosen": "alert_unit",
            "confidence": 0.9,
        }
        for i in range(10)
    ]

    result = score_session(scenario=scenario, events=events, false_alarms=1)
    d_prime = result["detection"]["d_prime"]

    # Target hand-computed value is approximately 1.845
    hand_computed = 1.84476
    assert abs(d_prime - hand_computed) < 0.01, f"d_prime {d_prime} does not match hand-computed {hand_computed}"


def test_perfect_trainee_overall_score():
    """Requirement: Perfect trainee (all detected, correct class, best response, high confidence) gives overall > 0.8."""
    scenario = generate_scenario(rng=123)
    tree = load_decision_tree()
    rules = tree.get("rules", {})

    events = []
    for obj in scenario["objects"]:
        rule_key = f"{obj['true_class']}|{obj['behaviour_label']}"
        rule = rules.get(rule_key, {})
        expected_level = rule.get("expected_threat_level", 1)

        # Pick the response with the highest score (1.0)
        responses = rule.get("responses", {})
        best_response = max(responses.items(), key=lambda item: item[1])[0]

        events.append(
            {
                "object_id": obj["id"],
                "detected": True,
                "detect_time_s": 1.0,  # Fast detection well within limits
                "classified_as": obj["true_class"],  # Perfectly classified
                "threat_level_rated": expected_level,  # Correct threat level
                "response_chosen": best_response,  # Best non-kinetic response
                "confidence": 0.98,  # Highly calibrated confidence
            }
        )

    result = score_session(scenario=scenario, events=events, false_alarms=0)

    assert result["overall"] > 0.8, f"Expected overall > 0.8, got {result['overall']}"
    assert result["detection_score"] > 0.7
    assert result["classification_score"] == 1.0
    assert result["decision_score"] == 1.0
    assert result["timeliness_score"] > 0.8
    assert result["calibration_score"] > 0.9


def test_miss_everything_trainee():
    """Requirement: Trainee who misses everything gives detection_score near 0 and overall < 0.3."""
    scenario = generate_scenario(rng=456)

    # No detections at all
    events = [
        {
            "object_id": obj["id"],
            "detected": False,
            "detect_time_s": 0.0,
            "classified_as": "unknown",
            "threat_level_rated": 0,
            "response_chosen": "ignore",
            "confidence": 0.0,
        }
        for obj in scenario["objects"]
    ]

    result = score_session(scenario=scenario, events=events, false_alarms=4)

    assert result["detection_score"] <= 0.15, f"Expected detection_score near 0, got {result['detection_score']}"
    assert result["overall"] < 0.3, f"Expected overall < 0.3, got {result['overall']}"


def test_overconfident_vs_hedged_wrong():
    """Requirement: Overconfident-wrong (confidence 0.95 on wrong class) gets lower calibration_score than hedged-wrong (0.5)."""
    scenario = {
        "scenario_id": "test_cal_scenario",
        "cell": ["day", "clear", "open", "EO", "none", "none"],
        "factors": {"distractors": "none"},
        "objects": [
            {
                "id": "obj_1",
                "true_class": "multirotor",
                "true_threat_level": 2,
                "behaviour_label": "suspicious",
            },
            {
                "id": "obj_2",
                "true_class": "fixed_wing_uav",
                "true_threat_level": 3,
                "behaviour_label": "suspicious",
            },
        ],
        "duration_s": 60.0,
        "difficulty_index": 0.5,
        "noise_windows": 3,
        "fingerprint": "fake_fp",
    }

    # Case A: Overconfident-wrong (confidence 0.95 on wrong class)
    events_overconfident = [
        {
            "object_id": "obj_1",
            "detected": True,
            "detect_time_s": 5.0,
            "classified_as": "bird",  # WRONG class
            "threat_level_rated": 0,
            "response_chosen": "ignore",
            "confidence": 0.95,
        },
        {
            "object_id": "obj_2",
            "detected": True,
            "detect_time_s": 5.0,
            "classified_as": "balloon",  # WRONG class
            "threat_level_rated": 0,
            "response_chosen": "ignore",
            "confidence": 0.95,
        },
    ]

    # Case B: Hedged-wrong (confidence 0.5 on wrong class)
    events_hedged = [
        {
            "object_id": "obj_1",
            "detected": True,
            "detect_time_s": 5.0,
            "classified_as": "bird",  # WRONG class
            "threat_level_rated": 0,
            "response_chosen": "ignore",
            "confidence": 0.50,
        },
        {
            "object_id": "obj_2",
            "detected": True,
            "detect_time_s": 5.0,
            "classified_as": "balloon",  # WRONG class
            "threat_level_rated": 0,
            "response_chosen": "ignore",
            "confidence": 0.50,
        },
    ]

    result_overconfident = score_session(scenario=scenario, events=events_overconfident, false_alarms=0)
    result_hedged = score_session(scenario=scenario, events=events_hedged, false_alarms=0)

    cal_overconfident = result_overconfident["calibration_score"]
    cal_hedged = result_hedged["calibration_score"]

    assert cal_overconfident < cal_hedged, (
        f"Overconfident wrong ({cal_overconfident}) should have lower calibration_score than hedged wrong ({cal_hedged})"
    )


def test_api_session_lifecycle(client):
    """Test full API session lifecycle: POST /session/start -> POST /session/result."""
    start_resp = client.post("/session/start", json={"trainee_id": "trainee_eval_01"})
    assert start_resp.status_code == 200
    start_data = start_resp.json()

    session_id = start_data["session_id"]
    scenario = start_data["scenario"]
    assert "noise_windows" in scenario

    events = [
        {
            "object_id": obj["id"],
            "detected": True,
            "detect_time_s": 2.0,
            "classified_as": obj["true_class"],
            "threat_level_rated": obj["true_threat_level"],
            "response_chosen": "monitor",
            "confidence": 0.85,
        }
        for obj in scenario["objects"]
    ]

    result_resp = client.post(
        "/session/result",
        json={
            "session_id": session_id,
            "events": events,
            "false_alarms": 0,
        },
    )
    assert result_resp.status_code == 200
    result_data = result_resp.json()

    assert "overall" in result_data
    assert "detection" in result_data
    assert "classification" in result_data
    assert "decision" in result_data
    assert "timeliness" in result_data
    assert "calibration" in result_data
    assert "skill_scores" in result_data


def test_false_alarms_far_above_noise_windows_never_gives_nan():
    """Verify false_alarms far above noise_windows never gives nan and records raw and scored counts."""
    scenario = {
        "scenario_id": "test_high_fa",
        "cell": ["day", "clear", "open", "EO", "none", "none"],
        "objects": [
            {
                "id": "obj_1",
                "true_class": "multirotor",
                "true_threat_level": 2,
                "behaviour_label": "suspicious",
            }
        ],
        "duration_s": 60.0,
        "difficulty_index": 0.5,
        "noise_windows": 3,
    }
    events = [
        {
            "object_id": "obj_1",
            "detected": True,
            "detect_time_s": 5.0,
            "classified_as": "multirotor",
            "threat_level_rated": 2,
            "response_chosen": "alert_unit",
            "confidence": 0.9,
        }
    ]

    result = score_session(scenario=scenario, events=events, false_alarms=100)

    assert np.isfinite(result["detection_score"])
    assert not np.isnan(result["detection_score"])
    assert np.isfinite(result["overall"])
    assert not np.isnan(result["overall"])
    assert np.isfinite(result["detection"]["d_prime"])
    assert np.isfinite(result["detection"]["criterion_c"])
    assert result["false_alarms_raw"] == 100
    assert result["false_alarms_scored"] == 3
    assert result["detection"]["false_alarms_raw"] == 100
    assert result["detection"]["false_alarms_scored"] == 3


def test_zero_objects_returns_finite_numbers():
    """Verify zero objects in scenario still returns finite numbers without NaN."""
    scenario = {
        "scenario_id": "test_zero_obj",
        "cell": ["day", "clear", "open", "EO", "none", "none"],
        "objects": [],
        "duration_s": 60.0,
        "difficulty_index": 0.5,
        "noise_windows": 3,
    }
    result = score_session(scenario=scenario, events=[], false_alarms=5)

    assert np.isfinite(result["detection_score"])
    assert not np.isnan(result["detection_score"])
    assert np.isfinite(result["overall"])
    assert not np.isnan(result["overall"])
    assert np.isfinite(result["detection"]["d_prime"])
    assert np.isfinite(result["detection"]["criterion_c"])
    assert result["detection"]["hits"] == 0
    assert result["detection"]["n_objects"] == 0


def test_zero_noise_windows_returns_finite_numbers():
    """Verify zero noise_windows still returns finite numbers without NaN."""
    scenario = {
        "scenario_id": "test_zero_noise",
        "cell": ["day", "clear", "open", "EO", "none", "none"],
        "objects": [
            {
                "id": "obj_1",
                "true_class": "multirotor",
                "true_threat_level": 2,
                "behaviour_label": "suspicious",
            }
        ],
        "duration_s": 60.0,
        "difficulty_index": 0.5,
        "noise_windows": 0,
    }
    events = [
        {
            "object_id": "obj_1",
            "detected": True,
            "detect_time_s": 5.0,
            "classified_as": "multirotor",
            "threat_level_rated": 2,
            "response_chosen": "alert_unit",
            "confidence": 0.9,
        }
    ]
    result = score_session(scenario=scenario, events=events, false_alarms=5)

    assert np.isfinite(result["detection_score"])
    assert not np.isnan(result["detection_score"])
    assert np.isfinite(result["overall"])
    assert not np.isnan(result["overall"])
    assert np.isfinite(result["detection"]["d_prime"])
    assert np.isfinite(result["detection"]["criterion_c"])
    assert result["false_alarms_raw"] == 5
    assert result["false_alarms_scored"] == 0
    assert result["detection"]["false_alarms_raw"] == 5
    assert result["detection"]["false_alarms_scored"] == 0


def test_twelve_objects_three_visible_gives_perfect_scores():
    """Requirement: a scenario with 12 generated objects where 3 are visible
    and all 3 are flagged and classified correctly gives Detection 100% and Classification 100%.
    """
    objects = []
    # 3 visible objects (in safe sky box, distance < 3000m, y > 0)
    for i in range(3):
        objects.append({
            "id": f"vis_obj_{i+1}",
            "true_class": "multirotor",
            "true_threat_level": 2,
            "behaviour_label": "suspicious",
            "start_position": [0.0, 1000.0, 150.0],
            "velocity": [0.0, 0.0, 0.0],
            "appears_at_time": 0.0,
        })
    # 9 non-visible objects (behind camera y = -500)
    for i in range(9):
        objects.append({
            "id": f"invis_obj_{i+1}",
            "true_class": "bird",
            "true_threat_level": 0,
            "behaviour_label": "benign",
            "start_position": [0.0, -500.0, 150.0],
            "velocity": [0.0, 0.0, 0.0],
            "appears_at_time": 0.0,
        })

    scenario = {
        "scenario_id": "test_12_targets_3_visible",
        "cell": ["day", "clear", "open", "EO", "none", "none"],
        "factors": {"time_of_day": "day", "terrain": "open", "distractors": "none"},
        "objects": objects,
        "duration_s": 60.0,
        "difficulty_index": 0.5,
        "noise_windows": 5,
        "fingerprint": "fake_fp",
    }

    # Trainee detects and correctly classifies all 3 visible objects
    tree = load_decision_tree()
    rules = tree.get("rules", {})
    rule = rules.get("multirotor|suspicious", {})
    best_response = max(rule.get("responses", {"alert_unit": 1.0}).items(), key=lambda x: x[1])[0]

    events = [
        {
            "object_id": f"vis_obj_{i+1}",
            "detected": True,
            "detect_time_s": 2.0,
            "classified_as": "multirotor",
            "threat_level_rated": 2,
            "response_chosen": best_response,
            "confidence": 0.95,
        }
        for i in range(3)
    ]

    result = score_session(scenario=scenario, events=events, false_alarms=0)

    # Scored objects must be exactly the 3 visible ones
    assert set(result["scored_objects"]) == {"vis_obj_1", "vis_obj_2", "vis_obj_3"}
    assert len(result["not_scored"]) == 9
    assert set(result["not_scored"]) == {f"invis_obj_{i+1}" for i in range(9)}

    # Detection 100% and Classification 100%
    assert result["detection"]["hits"] == 3
    assert result["detection"]["n_objects"] == 3
    assert result["detection_score"] == 1.0
    assert result["classification_score"] == 1.0
    assert result["missed_objects"] == []


def test_correct_classification_never_lowers_score():
    """Requirement: a correct classification never lowers the classification score.
    Also verified when missed objects or false alarms occur.
    """
    objects = [
        {
            "id": f"obj_{i+1}",
            "true_class": "multirotor",
            "true_threat_level": 2,
            "behaviour_label": "suspicious",
            "start_position": [0.0, 1000.0, 150.0],
            "velocity": [0.0, 0.0, 0.0],
            "appears_at_time": 0.0,
        }
        for i in range(3)
    ]
    scenario = {
        "scenario_id": "test_class_stability",
        "cell": ["day", "clear", "open", "EO", "none", "none"],
        "factors": {"time_of_day": "day", "terrain": "open", "distractors": "none"},
        "objects": objects,
        "duration_s": 60.0,
        "difficulty_index": 0.5,
        "noise_windows": 5,
        "fingerprint": "fake_fp",
    }

    # Event 1: 1 correct classification, 2 unflagged (missed)
    events_1 = [
        {
            "object_id": "obj_1",
            "detected": True,
            "detect_time_s": 2.0,
            "classified_as": "multirotor",
            "threat_level_rated": 2,
            "response_chosen": "alert_unit",
            "confidence": 0.9,
        }
    ]
    res1 = score_session(scenario=scenario, events=events_1, false_alarms=0)
    assert res1["classification_score"] == 1.0

    # Event 2: 2 correct classifications, 1 unflagged
    events_2 = events_1 + [
        {
            "object_id": "obj_2",
            "detected": True,
            "detect_time_s": 3.0,
            "classified_as": "multirotor",
            "threat_level_rated": 2,
            "response_chosen": "alert_unit",
            "confidence": 0.9,
        }
    ]
    res2 = score_session(scenario=scenario, events=events_2, false_alarms=0)
    assert res2["classification_score"] == 1.0
    assert res2["classification_score"] >= res1["classification_score"]

    # Even with 5 false alarms, classification score must not drop
    res2_with_fa = score_session(scenario=scenario, events=events_2, false_alarms=5)
    assert res2_with_fa["classification_score"] == 1.0


def test_not_scored_objects_never_appear_as_missed():
    """Requirement: not_scored objects never appear as missed."""
    objects = [
        # 2 visible objects
        {
            "id": "vis_1",
            "true_class": "multirotor",
            "true_threat_level": 2,
            "behaviour_label": "suspicious",
            "start_position": [0.0, 1000.0, 150.0],
            "velocity": [0.0, 0.0, 0.0],
            "appears_at_time": 0.0,
        },
        {
            "id": "vis_2",
            "true_class": "bird",
            "true_threat_level": 0,
            "behaviour_label": "benign",
            "start_position": [50.0, 1200.0, 200.0],
            "velocity": [0.0, 0.0, 0.0],
            "appears_at_time": 0.0,
        },
        # 3 never visible objects (behind camera y = -300)
        {
            "id": "invis_1",
            "true_class": "multirotor",
            "true_threat_level": 2,
            "behaviour_label": "suspicious",
            "start_position": [0.0, -300.0, 150.0],
            "velocity": [0.0, 0.0, 0.0],
            "appears_at_time": 0.0,
        },
        {
            "id": "invis_2",
            "true_class": "fixed_wing_uav",
            "true_threat_level": 3,
            "behaviour_label": "hostile",
            "start_position": [0.0, -600.0, 150.0],
            "velocity": [0.0, 0.0, 0.0],
            "appears_at_time": 0.0,
        },
        {
            "id": "invis_3",
            "true_class": "unknown",
            "true_threat_level": 1,
            "behaviour_label": "benign",
            "start_position": [0.0, -900.0, 150.0],
            "velocity": [0.0, 0.0, 0.0],
            "appears_at_time": 0.0,
        },
    ]

    scenario = {
        "scenario_id": "test_not_scored_disjoint_missed",
        "cell": ["day", "clear", "open", "EO", "none", "none"],
        "factors": {"time_of_day": "day", "terrain": "open", "distractors": "none"},
        "objects": objects,
        "duration_s": 60.0,
        "difficulty_index": 0.5,
        "noise_windows": 5,
        "fingerprint": "fake_fp",
    }

    # Case A: Trainee misses everything (no detections)
    result_miss_all = score_session(scenario=scenario, events=[], false_alarms=0)
    assert set(result_miss_all["not_scored"]) == {"invis_1", "invis_2", "invis_3"}
    assert set(result_miss_all["missed_objects"]) == {"vis_1", "vis_2"}
    assert set(result_miss_all["not_scored"]).isdisjoint(set(result_miss_all["missed_objects"]))

    # Case B: Trainee flags 1 visible object, misses 1 visible object
    events_partial = [
        {
            "object_id": "vis_1",
            "detected": True,
            "detect_time_s": 4.0,
            "classified_as": "multirotor",
            "threat_level_rated": 2,
            "response_chosen": "alert_unit",
            "confidence": 0.9,
        }
    ]
    result_partial = score_session(scenario=scenario, events=events_partial, false_alarms=0)
    assert set(result_partial["not_scored"]) == {"invis_1", "invis_2", "invis_3"}
    assert result_partial["missed_objects"] == ["vis_2"]
    assert set(result_partial["not_scored"]).isdisjoint(set(result_partial["missed_objects"]))


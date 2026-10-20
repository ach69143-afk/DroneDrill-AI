"""DroneDrill AI - Session Flow and Robustness Integration Tests.

Tests:
1. POST /session/start test mode -> POST /session/result with client-style mixed events (nulls/missing keys).
2. Practice mode session with client-style mixed events.
3. /session/next adaptive session with client-style mixed events.
4. Scripted scenario session with client-style mixed events.
5. Bad events resilience: countermeasure_simulated, unknown responses, NaN, None, missing keys, invalid types.
6. Input validation: clear 422/400/404 messages on invalid inputs, never 500.
7. 1000 generated scenarios (practice and held-out) validity check (>=6 consecutive seconds visible on-screen).
"""

import math
import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.factors import HELD_OUT_CELLS, PRACTICE_CELLS
from app.generator import generate_scenario, generate_for_cell
from app.sensor_view import check_main_view_visibility


@pytest.fixture
def client():
    return TestClient(app)


def _build_client_style_events(scenario_objects, detect_first_n=1):
    """Build events payload exactly as client/sim.js and client/app.js construct it."""
    events = []
    for idx, obj in enumerate(scenario_objects):
        oid = obj["id"]
        if idx < detect_first_n:
            events.append(
                {
                    "object_id": oid,
                    "detected": True,
                    "detect_time_s": 5.2,
                    "classified_as": obj.get("true_class", "multirotor"),
                    "threat_level_rated": obj.get("true_threat_level", 1),
                    "response_chosen": "monitor",
                    "confidence": 0.85,
                }
            )
        else:
            # Undetected object sent with null values
            events.append(
                {
                    "object_id": oid,
                    "detected": False,
                    "detect_time_s": None,
                    "classified_as": None,
                    "threat_level_rated": None,
                    "response_chosen": None,
                    "confidence": None,
                }
            )
    return events


def test_session_result_test_mode_held_out_scenario(client):
    """Bug 1: Test Mode held-out scenario with client-style mixed events must succeed with 200, not 500."""
    trainee_id = f"t1_{uuid.uuid4().hex[:6]}"
    start_resp = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "test"})
    assert start_resp.status_code == 200
    start_data = start_resp.json()
    session_id = start_data["session_id"]
    scenario = start_data["scenario"]
    assert tuple(scenario["cell"]) in HELD_OUT_CELLS

    events = _build_client_style_events(scenario["objects"], detect_first_n=1)
    result_resp = client.post(
        "/session/result",
        json={"session_id": session_id, "events": events, "false_alarms": 1},
    )

    assert result_resp.status_code == 200, f"Expected 200, got {result_resp.status_code}: {result_resp.text}"
    data = result_resp.json()
    assert "overall" in data
    assert "detection_score" in data
    assert "classification_score" in data
    assert "decision_score" in data
    assert "timeliness_score" in data
    assert "calibration_score" in data
    assert 0.0 <= data["overall"] <= 1.0


def test_session_result_practice_mode(client):
    """Practice mode session with mixed client events succeeds with 200."""
    trainee_id = f"t_prac_{uuid.uuid4().hex[:6]}"
    start_resp = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "practice"})
    assert start_resp.status_code == 200
    start_data = start_resp.json()
    session_id = start_data["session_id"]
    scenario = start_data["scenario"]

    events = _build_client_style_events(scenario["objects"], detect_first_n=1)
    result_resp = client.post(
        "/session/result",
        json={"session_id": session_id, "events": events, "false_alarms": 0},
    )

    assert result_resp.status_code == 200
    data = result_resp.json()
    assert 0.0 <= data["overall"] <= 1.0


def test_session_result_session_next_flow(client):
    """Adaptive practice session (/session/next) with mixed client events succeeds with 200."""
    trainee_id = f"t_next_{uuid.uuid4().hex[:6]}"
    next_resp = client.post("/session/next", json={"trainee_id": trainee_id})
    assert next_resp.status_code == 200
    next_data = next_resp.json()
    session_id = next_data["session_id"]
    scenario = next_data["scenario"]

    events = _build_client_style_events(scenario["objects"], detect_first_n=1)
    result_resp = client.post(
        "/session/result",
        json={"session_id": session_id, "events": events, "false_alarms": 2},
    )

    assert result_resp.status_code == 200
    data = result_resp.json()
    assert 0.0 <= data["overall"] <= 1.0


def test_session_result_scripted_flow(client):
    """Scripted scenario session with mixed client events succeeds with 200."""
    trainee_id = f"t_script_{uuid.uuid4().hex[:6]}"
    start_resp = client.post(
        "/session/start",
        json={
            "trainee_id": trainee_id,
            "mode": "practice",
            "scripted_id": "scripted_01_day_clear_multirotor",
        },
    )
    assert start_resp.status_code == 200
    start_data = start_resp.json()
    session_id = start_data["session_id"]
    scenario = start_data["scenario"]

    events = _build_client_style_events(scenario["objects"], detect_first_n=1)
    result_resp = client.post(
        "/session/result",
        json={"session_id": session_id, "events": events, "false_alarms": 0},
    )

    assert result_resp.status_code == 200
    data = result_resp.json()
    assert 0.0 <= data["overall"] <= 1.0


def test_bad_events_never_crash_session(client):
    """One bad event (unknown response, countermeasure_simulated, NaN, None, missing keys, invalid types) must never crash."""
    trainee_id = f"t_bad_{uuid.uuid4().hex[:6]}"
    start_resp = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "practice"})
    session_id = start_resp.json()["session_id"]
    scenario = start_resp.json()["scenario"]
    objs = scenario["objects"]

    oid_0 = objs[0]["id"] if len(objs) > 0 else "obj_1"
    oid_1 = objs[1]["id"] if len(objs) > 1 else "obj_2"

    bad_events = [
        # Response countermeasure_simulated
        {
            "object_id": oid_0,
            "detected": True,
            "detect_time_s": 4.0,
            "classified_as": "multirotor",
            "threat_level_rated": 3,
            "response_chosen": "countermeasure_simulated",
            "confidence": 0.9,
        },
        # Unknown response not in decision tree
        {
            "object_id": oid_1,
            "detected": True,
            "detect_time_s": 7.0,
            "classified_as": "bird",
            "threat_level_rated": "invalid_level",
            "response_chosen": "non_standard_tactical_action",
            "confidence": "NaN",
        },
        # Empty dict
        {},
        # Non-dict item
        "corrupted_event_string",
        # None and missing values
        {
            "object_id": "non_existent_obj",
            "detected": True,
            "detect_time_s": None,
            "confidence": None,
            "classified_as": None,
            "threat_level_rated": None,
            "response_chosen": None,
        },
    ]

    result_resp = client.post(
        "/session/result",
        json={"session_id": session_id, "events": bad_events, "false_alarms": 0},
    )

    assert result_resp.status_code == 200
    data = result_resp.json()
    assert "overall" in data
    assert 0.0 <= data["overall"] <= 1.0
    assert not math.isnan(data["overall"])


def test_endpoint_input_validation(client):
    """Invalid input payloads must return clear 422 or 400 status codes, never 500."""
    # 1. Empty session_id -> 422
    resp_empty = client.post("/session/result", json={"session_id": "   ", "events": []})
    assert resp_empty.status_code in (400, 422)

    # 2. Negative false_alarms -> 422
    resp_neg_fa = client.post("/session/result", json={"session_id": "valid_id", "false_alarms": -5})
    assert resp_neg_fa.status_code in (400, 422)

    # 3. Non-existent session_id -> 404
    resp_not_found = client.post("/session/result", json={"session_id": "non_existent_id_12345", "events": []})
    assert resp_not_found.status_code == 404

    # 4. Events not a list -> 422
    resp_not_list = client.post("/session/result", json={"session_id": "any_id", "events": "not_a_list"})
    assert resp_not_list.status_code == 422


def test_one_thousand_scenarios_validity_rule():
    """Requirement: Every scenario over 1000 generated scenarios (practice and held-out)
    must have at least one object on-screen and visible in the MAIN view for >= 6 consecutive seconds.
    """
    # 500 practice scenarios
    for _ in range(500):
        scen = generate_scenario(allow_held_out=False)
        assert check_main_view_visibility(scen, min_consecutive_s=6.0), (
            f"Practice scenario {scen['scenario_id']} failed 6-second visibility rule! Cell: {scen['cell']}"
        )

    # 500 held-out / all-cell scenarios
    for _ in range(500):
        scen = generate_scenario(allow_held_out=True)
        assert check_main_view_visibility(scen, min_consecutive_s=6.0), (
            f"Held-out scenario {scen['scenario_id']} failed 6-second visibility rule! Cell: {scen['cell']}"
        )

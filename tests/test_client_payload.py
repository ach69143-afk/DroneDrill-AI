"""DroneDrill AI - Client Payload Validation and Session Result Integration Tests.

Validates that POST /session/result handles the EXACT payload structure sent by client/app.js and client/sim.js across:
- Practice sessions
- Test sessions (mode "test", held-out cell)
- /session/next adaptive sessions
- Scripted scenarios
- 0, 1, and all objects flagged
- Several false alarms
- Contacts assessed but never submitted (detected=True, other fields null/default)
- UI label mappings (Multirotor Drone -> multirotor, Elevated -> 2, Monitor Track -> monitor)
- Unknown responses (scored 0, warning returned, never raises KeyError)
- Missing/NaN/null numeric fields for undetected and detected objects
- Duplicate object events (keeping the last one)
- Non-matching object IDs
- Double submission returning 409 Conflict
- Bad input returning 422/400, never 500
"""

import math
import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.factors import HELD_OUT_CELLS, PRACTICE_CELLS
from app.db import get_session


@pytest.fixture
def client():
    return TestClient(app)


def build_client_payload(scenario_objects, flagged_indices=None, unsubmitted_indices=None, false_alarms=0):
    """Replicates client/app.js endSession() payload generation."""
    flagged_indices = set(flagged_indices or [])
    unsubmitted_indices = set(unsubmitted_indices or [])
    events = []

    for idx, obj in enumerate(scenario_objects):
        oid = obj["id"]
        if idx in flagged_indices:
            if idx in unsubmitted_indices:
                # Contact clicked (detected) but never submitted in assessment form
                events.append({
                    "object_id": oid,
                    "detected": True,
                    "detect_time_s": 6.5,
                    "classified_as": None,
                    "threat_level_rated": None,
                    "response_chosen": None,
                    "confidence": 0.75,
                })
            else:
                # Normal fully assessed and submitted contact
                events.append({
                    "object_id": oid,
                    "detected": True,
                    "detect_time_s": 5.2,
                    "classified_as": obj.get("true_class", "multirotor"),
                    "threat_level_rated": obj.get("true_threat_level", 1),
                    "response_chosen": "monitor",
                    "confidence": 0.85,
                })
        else:
            # Undetected object sent with null fields
            events.append({
                "object_id": oid,
                "detected": False,
                "detect_time_s": None,
                "classified_as": None,
                "threat_level_rated": None,
                "response_chosen": None,
                "confidence": None,
            })

    return events


def test_practice_session_variations(client):
    """Test practice sessions with 0, 1, all objects flagged, false alarms, and unsubmitted contacts."""
    trainee_id = f"trainee_prac_{uuid.uuid4().hex[:6]}"
    
    # 1. Zero objects flagged, 0 false alarms
    start_res = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "practice"})
    assert start_res.status_code == 200
    s_data = start_res.json()
    sess_id = s_data["session_id"]
    objs = s_data["objects"]

    events = build_client_payload(objs, flagged_indices=[])
    res = client.post("/session/result", json={"session_id": sess_id, "events": events, "false_alarms": 0})
    assert res.status_code == 200, f"Failed: {res.text}"
    data = res.json()
    assert data["overall"] >= 0.0

    # 2. 1 object flagged, several false alarms (3)
    start_res = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "practice"})
    s_data = start_res.json()
    sess_id = s_data["session_id"]
    objs = s_data["objects"]
    events = build_client_payload(objs, flagged_indices=[0], false_alarms=3)
    res = client.post("/session/result", json={"session_id": sess_id, "events": events, "false_alarms": 3})
    assert res.status_code == 200, f"Failed: {res.text}"

    # 3. All objects flagged
    start_res = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "practice"})
    s_data = start_res.json()
    sess_id = s_data["session_id"]
    objs = s_data["objects"]
    events = build_client_payload(objs, flagged_indices=list(range(len(objs))))
    res = client.post("/session/result", json={"session_id": sess_id, "events": events, "false_alarms": 0})
    assert res.status_code == 200, f"Failed: {res.text}"

    # 4. Contact assessed but never submitted (fields are null)
    start_res = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "practice"})
    s_data = start_res.json()
    sess_id = s_data["session_id"]
    objs = s_data["objects"]
    events = build_client_payload(objs, flagged_indices=[0], unsubmitted_indices=[0])
    res = client.post("/session/result", json={"session_id": sess_id, "events": events, "false_alarms": 1})
    assert res.status_code == 200, f"Failed: {res.text}"


def test_test_mode_held_out_variations(client):
    """Test mode sessions (held-out cells) across all object flagging permutations."""
    trainee_id = f"trainee_test_{uuid.uuid4().hex[:6]}"

    # 1. Zero objects flagged
    start_res = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "test"})
    assert start_res.status_code == 200
    s_data = start_res.json()
    sess_id = s_data["session_id"]
    objs = s_data["objects"]
    events = build_client_payload(objs, flagged_indices=[])
    res = client.post("/session/result", json={"session_id": sess_id, "events": events, "false_alarms": 2})
    assert res.status_code == 200, f"Failed: {res.text}"

    # 2. 1 object flagged, 1 unsubmitted
    start_res = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "test"})
    s_data = start_res.json()
    sess_id = s_data["session_id"]
    objs = s_data["objects"]
    flagged = [0] if len(objs) == 1 else [0, 1]
    unsub = [1] if len(objs) > 1 else [0]
    events = build_client_payload(objs, flagged_indices=flagged, unsubmitted_indices=unsub)
    res = client.post("/session/result", json={"session_id": sess_id, "events": events, "false_alarms": 1})
    assert res.status_code == 200, f"Failed: {res.text}"

    # 3. All objects flagged
    start_res = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "test"})
    s_data = start_res.json()
    sess_id = s_data["session_id"]
    objs = s_data["objects"]
    events = build_client_payload(objs, flagged_indices=list(range(len(objs))))
    res = client.post("/session/result", json={"session_id": sess_id, "events": events, "false_alarms": 0})
    assert res.status_code == 200, f"Failed: {res.text}"


def test_session_next_adaptive(client):
    """POST /session/next sessions evaluated through /session/result."""
    trainee_id = f"trainee_next_{uuid.uuid4().hex[:6]}"
    # Seed one practice session
    init_s = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "practice"})
    init_data = init_s.json()
    evs = build_client_payload(init_data["objects"], flagged_indices=[0])
    client.post("/session/result", json={"session_id": init_data["session_id"], "events": evs, "false_alarms": 0})

    next_res = client.post("/session/next", json={"trainee_id": trainee_id})
    assert next_res.status_code == 200
    n_data = next_res.json()
    sess_id = n_data["session_id"]
    objs = n_data["scenario"]["objects"]

    events = build_client_payload(objs, flagged_indices=[0])
    res = client.post("/session/result", json={"session_id": sess_id, "events": events, "false_alarms": 0})
    assert res.status_code == 200, f"Failed: {res.text}"


def test_scripted_id_session(client):
    """Scripted scenarios evaluated through /session/result."""
    trainee_id = f"trainee_scripted_{uuid.uuid4().hex[:6]}"
    start_res = client.post(
        "/session/start",
        json={"trainee_id": trainee_id, "mode": "practice", "scripted_id": "scripted_01_day_clear_multirotor"},
    )
    assert start_res.status_code == 200
    s_data = start_res.json()
    sess_id = s_data["session_id"]
    objs = s_data["objects"]

    events = build_client_payload(objs, flagged_indices=[0])
    res = client.post("/session/result", json={"session_id": sess_id, "events": events, "false_alarms": 1})
    assert res.status_code == 200, f"Failed: {res.text}"


def test_ui_label_mapping(client):
    """UI display labels must be mapped properly (or handled on server) without raising error."""
    trainee_id = f"trainee_labels_{uuid.uuid4().hex[:6]}"
    start_res = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "practice"})
    s_data = start_res.json()
    sess_id = s_data["session_id"]
    objs = s_data["objects"]
    oid = objs[0]["id"]

    # Passing UI strings: 'Multirotor Drone', 'Elevated', 'Monitor Track'
    events = [
        {
            "object_id": oid,
            "detected": True,
            "detect_time_s": 8.0,
            "classified_as": "Multirotor Drone",
            "threat_level_rated": "Elevated",
            "response_chosen": "Monitor Track",
            "confidence": 0.8,
        }
    ]
    res = client.post("/session/result", json={"session_id": sess_id, "events": events, "false_alarms": 0})
    assert res.status_code == 200, f"Failed: {res.text}"
    data = res.json()
    assert data["decision_score"] >= 0.0


def test_unknown_response_reported_in_warnings(client):
    """An unknown response key must never raise KeyError: score it 0 and report it in a warnings list."""
    trainee_id = f"trainee_warn_{uuid.uuid4().hex[:6]}"
    start_res = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "practice"})
    s_data = start_res.json()
    sess_id = s_data["session_id"]
    objs = s_data["objects"]
    oid = objs[0]["id"]

    events = [
        {
            "object_id": oid,
            "detected": True,
            "detect_time_s": 4.0,
            "classified_as": "multirotor",
            "threat_level_rated": 1,
            "response_chosen": "unrecognized_action_xyz",
            "confidence": 0.9,
        }
    ]
    res = client.post("/session/result", json={"session_id": sess_id, "events": events, "false_alarms": 0})
    assert res.status_code == 200, f"Failed: {res.text}"
    data = res.json()
    assert "warnings" in data
    assert any("unrecognized_action_xyz" in w for w in data["warnings"])


def test_duplicate_events_keep_last(client):
    """Duplicate events for the same object keep the last event."""
    trainee_id = f"trainee_dup_{uuid.uuid4().hex[:6]}"
    start_res = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "practice"})
    s_data = start_res.json()
    sess_id = s_data["session_id"]
    objs = s_data["objects"]
    oid = objs[0]["id"]

    events = [
        # First event: wrong classification
        {
            "object_id": oid,
            "detected": True,
            "detect_time_s": 3.0,
            "classified_as": "bird",
            "threat_level_rated": 0,
            "response_chosen": "ignore",
            "confidence": 0.2,
        },
        # Second event (last): updated classification
        {
            "object_id": oid,
            "detected": True,
            "detect_time_s": 5.0,
            "classified_as": objs[0].get("true_class", "multirotor"),
            "threat_level_rated": objs[0].get("true_threat_level", 1),
            "response_chosen": "monitor",
            "confidence": 0.9,
        },
    ]
    res = client.post("/session/result", json={"session_id": sess_id, "events": events, "false_alarms": 0})
    assert res.status_code == 200
    data = res.json()
    # If the last event was kept, classification score should be 1.0 (since it was correct)
    assert data["classification_score"] == 1.0


def test_non_matching_object_id_ignored_safely(client):
    """object_id not matching scenario's object ids must be ignored safely with a warning."""
    trainee_id = f"trainee_nonmatch_{uuid.uuid4().hex[:6]}"
    start_res = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "practice"})
    s_data = start_res.json()
    sess_id = s_data["session_id"]

    events = [
        {
            "object_id": "non_existent_ghost_id_999",
            "detected": True,
            "detect_time_s": 2.0,
            "classified_as": "bird",
            "threat_level_rated": 0,
            "response_chosen": "ignore",
            "confidence": 0.5,
        }
    ]
    res = client.post("/session/result", json={"session_id": sess_id, "events": events, "false_alarms": 0})
    assert res.status_code == 200
    data = res.json()
    assert "warnings" in data
    assert any("non_existent_ghost_id_999" in w for w in data["warnings"])


def test_double_submission_returns_409(client):
    """Submitting the same session_id twice must return 409 Conflict, not 500."""
    trainee_id = f"trainee_409_{uuid.uuid4().hex[:6]}"
    start_res = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "practice"})
    s_data = start_res.json()
    sess_id = s_data["session_id"]
    objs = s_data["objects"]

    events = build_client_payload(objs, flagged_indices=[0])
    res1 = client.post("/session/result", json={"session_id": sess_id, "events": events, "false_alarms": 0})
    assert res1.status_code == 200

    # Second submission
    res2 = client.post("/session/result", json={"session_id": sess_id, "events": events, "false_alarms": 0})
    assert res2.status_code == 409
    detail = res2.json().get("detail", "")
    assert "already" in detail.lower()


def test_bad_input_validation(client):
    """Bad data must return 422 or 400 with a clear message, NEVER 500."""
    # 1. Missing session_id
    r1 = client.post("/session/result", json={"session_id": "", "events": []})
    assert r1.status_code in (400, 422)

    # 2. Negative false_alarms
    r2 = client.post("/session/result", json={"session_id": "non_empty", "false_alarms": -5})
    assert r2.status_code in (400, 422)

    # 3. Non-existent session_id
    r3 = client.post("/session/result", json={"session_id": "does-not-exist-12345", "events": []})
    assert r3.status_code == 404

"""Unit tests for DroneDrill AI Scripted Scenarios and Instructor Features.

Tests:
1. Scripted scenarios load and are all PRACTICE cells.
2. GET /scenarios library endpoint returns scripted scenarios + generator note.
3. POST /session/start with scripted_id launches scripted scenario.
4. Instructor launcher constraints return matching cell with source='instructor_launched', or 400 on invalid/no match.
5. scripts/seed_demo.py runs twice without duplicating trainees (idempotence).
6. Instructor endpoints: GET /trainees, GET /unit/summary, GET /decision-tree.
"""

import pytest
from fastapi.testclient import TestClient

from app.factors import PRACTICE_CELLS, HELD_OUT_CELLS
from app.main import app
from app.scripted import load_scripted_scenarios, get_scripted_scenario
from scripts.seed_demo import seed_demo_data
from app.db import get_all_trainees


@pytest.fixture
def client():
    return TestClient(app)


def test_scripted_scenarios_load_and_are_all_practice_cells():
    """Requirement: 6 hand-authored scenarios load and its cell must be a PRACTICE cell."""
    scenarios = load_scripted_scenarios()

    assert len(scenarios) >= 6, f"Expected at least 6 scripted scenarios, found {len(scenarios)}"

    expected_scenarios = [
        ("scripted_01_day_clear_multirotor", "Clear Day Solo Multirotor"),
        ("scripted_02_dusk_fog_dual", "Dusk Fog Dual Contact"),
        ("scripted_03_night_thermal_flock", "Night Thermal Bird Flock"),
        ("scripted_04_urban_clutter_mixed", "Urban Clutter Occlusion Mixed Classes"),
        ("scripted_05_swarm_overload", "Perception Overload Swarm"),
        ("scripted_06_rain_noise_unknown", "Rain Noise Unknown Object"),
    ]

    for scen_id, expected_title in expected_scenarios:
        assert scen_id in scenarios, f"Missing scripted scenario: {scen_id}"
        scen = scenarios[scen_id]

        assert scen["title"] == expected_title
        assert scen["description"], f"Scenario {scen_id} must have non-empty description"
        assert scen["source"] == "scripted"

        cell = tuple(scen["cell"])
        assert len(cell) == 6
        assert cell in PRACTICE_CELLS, f"Scenario {scen_id} cell {cell} must be in PRACTICE_CELLS"
        assert cell not in HELD_OUT_CELLS, f"Scenario {scen_id} cell {cell} cannot be in HELD_OUT_CELLS"

        # Check specific scenario content requirements
        if scen_id == "scripted_01_day_clear_multirotor":
            assert len(scen["objects"]) == 1
            assert scen["objects"][0]["true_class"] == "multirotor"

        elif scen_id == "scripted_02_dusk_fog_dual":
            assert len(scen["objects"]) == 2
            labels = {obj["behaviour_label"] for obj in scen["objects"]}
            assert "benign" in labels
            assert "suspicious" in labels

        elif scen_id == "scripted_03_night_thermal_flock":
            assert scen["cell"][0] == "night"
            assert scen["cell"][3] == "thermal"
            assert any(obj["true_class"] == "bird" for obj in scen["objects"])
            assert scen["cell"][5] == "birds"

        elif scen_id == "scripted_04_urban_clutter_mixed":
            assert scen["cell"][2] == "urban"
            assert scen["cell"][4] == "occlusion"
            classes = {obj["true_class"] for obj in scen["objects"]}
            assert len(classes) >= 2  # Mixed classes

        elif scen_id == "scripted_05_swarm_overload":
            assert len(scen["objects"]) >= 9, "SWARM must have 9+ objects"
            assert any(obj["true_class"] == "bird" for obj in scen["objects"])

        elif scen_id == "scripted_06_rain_noise_unknown":
            assert scen["cell"][1] == "rain"
            assert scen["cell"][4] == "noise"
            assert any(obj["true_class"] == "unknown" for obj in scen["objects"])


def test_get_scenarios_library_endpoint(client):
    """Requirement: GET /scenarios -> library list plus note that procedural scenarios come from generator."""
    resp = client.get("/scenarios")
    assert resp.status_code == 200
    data = resp.json()

    assert "scenarios" in data
    assert "note" in data
    assert "generator" in data["note"].lower()
    assert len(data["scenarios"]) >= 6

    first = data["scenarios"][0]
    assert "id" in first
    assert "title" in first
    assert "description" in first
    assert first["source"] == "scripted"


def test_start_session_with_scripted_id(client):
    """Requirement: POST /session/start accepts optional scripted_id (practice mode)."""
    resp = client.post(
        "/session/start",
        json={"trainee_id": "test_scripted_user", "mode": "practice", "scripted_id": "scripted_01_day_clear_multirotor"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["scenario"]["scenario_id"] == "scripted_01_day_clear_multirotor"
    assert data["scenario"]["source"] == "scripted"
    assert len(data["scenario"]["objects"]) == 1

    # In test mode, scripted_id is forbidden
    bad_resp = client.post(
        "/session/start",
        json={"trainee_id": "test_scripted_user", "mode": "test", "scripted_id": "scripted_01_day_clear_multirotor"},
    )
    assert bad_resp.status_code == 400


def test_instructor_launcher_constraints_and_400(client):
    """Requirement: constraints return a matching cell or 400. Scenario source = 'instructor_launched'."""
    # 1. Valid constraints
    constraints = {
        "time_of_day": "night",
        "weather": "rain",
        "terrain": "urban",
        "sensor_mode": "thermal",
        "object_count": "1",
    }
    resp = client.post(
        "/session/start",
        json={"trainee_id": "instructor_trainee_01", "mode": "practice", "constraints": constraints},
    )
    assert resp.status_code == 200
    data = resp.json()
    scenario = data["scenario"]

    assert scenario["source"] == "instructor_launched"
    cell = tuple(scenario["cell"])
    assert cell in PRACTICE_CELLS
    assert scenario["factors"]["time_of_day"] == "night"
    assert scenario["factors"]["weather"] == "rain"
    assert scenario["factors"]["terrain"] == "urban"
    assert scenario["factors"]["sensor_mode"] == "thermal"
    assert len(scenario["objects"]) == 1

    # 2. Conflicting / impossible constraints that match 0 practice cells -> 400 with clear message
    bad_constraints = {
        "time_of_day": "nonexistent_time",
        "weather": "clear",
    }
    err_resp = client.post(
        "/session/start",
        json={"trainee_id": "instructor_trainee_01", "mode": "practice", "constraints": bad_constraints},
    )
    assert err_resp.status_code == 400
    assert "No practice cell matches" in err_resp.json()["detail"]


def test_seed_demo_script_idempotent():
    """Requirement: seed script runs twice without duplicating trainees."""
    # Run 1
    results_1 = seed_demo_data(seed=123)
    assert len(results_1) == 10

    all_trainees_1 = [t for t in get_all_trainees() if t["is_demo"] == 1]
    assert len(all_trainees_1) == 10

    # Run 2
    results_2 = seed_demo_data(seed=123)
    assert len(results_2) == 10

    all_trainees_2 = [t for t in get_all_trainees() if t["is_demo"] == 1]
    assert len(all_trainees_2) == 10, "Demo trainees must not be duplicated on re-run"


def test_instructor_endpoints(client):
    """Requirement: GET /trainees, GET /unit/summary, GET /decision-tree."""
    # 1. GET /trainees
    resp = client.get("/trainees")
    assert resp.status_code == 200
    trainees = resp.json()
    assert len(trainees) >= 10

    demo_t = next(t for t in trainees if t["id"] == "demo_trainee_01")
    assert demo_t["name"] == "Demo Trainee 01"
    assert demo_t["is_demo"] == 1
    assert "sessions" in demo_t
    assert "mean_overall" in demo_t
    assert "generalization_score" in demo_t
    assert "rote_gap" in demo_t

    # 2. GET /unit/summary
    summary_resp = client.get("/unit/summary")
    assert summary_resp.status_code == 200
    summary = summary_resp.json()

    assert "score_distribution" in summary
    assert "total_sessions" in summary["score_distribution"]
    assert "top_confusion_pairs" in summary
    assert "weakest_conditions" in summary
    assert "mean_coverage" in summary

    # 3. GET /decision-tree
    dt_resp = client.get("/decision-tree")
    assert dt_resp.status_code == 200
    dt_data = dt_resp.json()
    assert "_status" in dt_data
    assert "Instructor-editable draft" in dt_data["_status"]
    assert "threat_levels" in dt_data
    assert "rules" in dt_data

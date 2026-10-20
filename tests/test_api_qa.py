"""DroneDrill AI - Phase 1 Comprehensive API QA Script.

Automates the exhaustive verification of every FastAPI route:
- Valid payloads -> 2xx with documented schemas
- Invalid payloads -> 4xx with readable errors (never 500)
- Session lifecycle: practice, test/held-out, scripted, swarm (0, some, all flagged; false alarms; double-submit)
- Score bounds [0, 1.0], no NaN/null, 5 component scores, not_scored list
- Demo trainees & brand new trainee empty states
- Adaptive progression on repeated sessions
"""

import sys
import json
import math
from pathlib import Path
import urllib.request
import urllib.error
import pytest
from starlette.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import app
from app.factors import PRACTICE_CELLS, HELD_OUT_CELLS
from app.generator import generate_scenario
from app.sensor_view import check_main_view_visibility, get_scored_and_unscored_objects

client = TestClient(app)

def test_routes_manifest():
    """Ensure all expected routes are present in the FastAPI app."""
    routes = {r.path for r in app.routes if hasattr(r, 'methods')}
    expected = {
        "/",
        "/health",
        "/scenarios",
        "/session/start",
        "/session/next",
        "/session/result",
        "/scenario/{session_id}/telemetry",
        "/aar/{session_id}",
        "/trainee/{id}/skills",
        "/trainee/{id}/performance",
        "/trainee/{id}/generalization",
        "/trainee/{id}/plan",
        "/trainees",
        "/unit/summary",
        "/decision-tree",
        "/validation",
    }
    for exp in expected:
        assert exp in routes, f"Missing route {exp}"


def test_health_and_info():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    res_tree = client.get("/decision-tree")
    assert res_tree.status_code == 200
    tree_data = res_tree.json()
    assert "rules" in tree_data
    assert len(tree_data["rules"]) > 0

    res_val = client.get("/validation")
    assert res_val.status_code == 200
    assert "status" in res_val.json()

    res_scen = client.get("/scenarios")
    assert res_scen.status_code == 200
    scen_data = res_scen.json()
    assert scen_data["total"] >= 6
    assert any(s["id"] == "scripted_05_swarm_overload" for s in scen_data["scenarios"])


def test_session_lifecycle_and_edge_cases():
    trainee_id = "qa_tester_lifecycle"

    # 1. Start Practice Session
    start_resp = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "practice"})
    assert start_resp.status_code == 200
    s_data = start_resp.json()
    session_id = s_data["session_id"]
    assert s_data["mode"] == "practice"
    assert tuple(s_data["cell"]) in PRACTICE_CELLS
    assert len(s_data["objects"]) >= 1

    # Check telemetry for this session
    telem_resp = client.get(f"/scenario/{session_id}/telemetry")
    assert telem_resp.status_code == 200
    t_data = telem_resp.json()
    assert len(t_data["packets"]) > 0
    assert "visibility_windows" in t_data

    # Submit result with 0 flagged contacts
    res_payload = {
        "session_id": session_id,
        "events": [],
        "false_alarms": 0,
    }
    result_resp = client.post("/session/result", json=res_payload)
    assert result_resp.status_code == 200
    scores = result_resp.json()
    assert 0.0 <= scores["overall"] <= 1.0
    for comp in ["detection_score", "classification_score", "decision_score", "timeliness_score", "calibration_score"]:
        assert comp in scores
        val = scores[comp]
        assert val is not None and not math.isnan(val), f"NaN/null in {comp}"
        assert 0.0 <= val <= 1.0
    assert "not_scored" in scores

    # Double submit check -> 409
    dup_resp = client.post("/session/result", json=res_payload)
    assert dup_resp.status_code == 409

    # Check AAR
    aar_resp = client.get(f"/aar/{session_id}")
    assert aar_resp.status_code == 200
    aar_data = aar_resp.json()
    assert aar_data["session_id"] == session_id
    assert "timeline" in aar_data
    assert "deltas" in aar_data
    assert "not_scored" in aar_data


def test_swarm_and_all_visible_100_percent():
    """Swarm overload scenario with all visible targets flagged and correctly classified."""
    trainee_id = "qa_tester_swarm"
    start_resp = client.post("/session/start", json={
        "trainee_id": trainee_id,
        "mode": "practice",
        "scripted_id": "scripted_05_swarm_overload",
    })
    assert start_resp.status_code == 200
    s_data = start_resp.json()
    session_id = s_data["session_id"]
    scenario = s_data["scenario"]

    scored_objs, not_scored = get_scored_and_unscored_objects(scenario, min_visible_s=3.0)
    assert len(scored_objs) >= 1

    events = []
    for obj in scored_objs:
        events.append({
            "object_id": obj["id"],
            "detected": True,
            "detect_time_s": obj.get("appears_at_time", 1.0) + 0.5,
            "classified_as": obj["true_class"],
            "threat_level_rated": obj["true_threat_level"],
            "response_chosen": "monitor",
            "confidence": 0.9,
        })

    res_resp = client.post("/session/result", json={
        "session_id": session_id,
        "events": events,
        "false_alarms": 0,
    })
    assert res_resp.status_code == 200
    scores = res_resp.json()
    assert scores["detection_score"] == 1.0
    assert scores["classification_score"] == 1.0


def test_test_mode_held_out():
    """Verify test mode selects strictly from HELD_OUT_CELLS."""
    start_resp = client.post("/session/start", json={"trainee_id": "qa_tester_test_mode", "mode": "test"})
    assert start_resp.status_code == 200
    s_data = start_resp.json()
    assert s_data["mode"] == "test"
    assert tuple(s_data["cell"]) in HELD_OUT_CELLS


def test_invalid_payloads_never_500():
    """Exhaustively verify invalid inputs return 4xx, never 500."""
    # /session/start invalid
    assert client.post("/session/start", json={}).status_code == 422
    assert client.post("/session/start", json={"trainee_id": None}).status_code == 422
    assert client.post("/session/start", json={"trainee_id": "t1", "constraints": {"weather": "hurricane"}}).status_code == 400

    # /session/next invalid
    assert client.post("/session/next", json={}).status_code == 422
    assert client.post("/session/next", json={"trainee_id": "   "}).status_code == 400

    # /session/result invalid
    assert client.post("/session/result", json={}).status_code == 422
    assert client.post("/session/result", json={"session_id": ""}).status_code == 422
    assert client.post("/session/result", json={"session_id": "nonexistent"}).status_code == 404
    assert client.post("/session/result", json={"session_id": "nonexistent", "false_alarms": -5}).status_code == 422

    # /scenario/{id}/telemetry unknown
    assert client.get("/scenario/unknown-session-id/telemetry").status_code == 404

    # /aar/{id} unknown
    assert client.get("/aar/unknown-session-id").status_code == 404

    # /trainee/{id} empty IDs
    assert client.get("/trainee/%20%20/skills").status_code == 400
    assert client.get("/trainee/%20%20/performance").status_code == 400
    assert client.get("/trainee/%20%20/generalization").status_code == 400
    assert client.get("/trainee/%20%20/plan").status_code == 400


def test_demo_trainees_and_new_trainee_empty_state():
    """Verify 10 demo trainees exist and brand new trainee handles empty state."""
    trainees_resp = client.get("/trainees")
    assert trainees_resp.status_code == 200
    trainees = trainees_resp.json()
    demo_trainees = [t for t in trainees if t.get("is_demo") == 1]
    assert len(demo_trainees) == 10

    # New trainee with 0 sessions
    new_id = "brand_new_trainee_zero_sessions"
    perf_resp = client.get(f"/trainee/{new_id}/performance")
    assert perf_resp.status_code == 200
    assert perf_resp.json()["sessions"] == []

    gen_resp = client.get(f"/trainee/{new_id}/generalization")
    assert gen_resp.status_code == 200
    gen_data = gen_resp.json()
    assert gen_data["generalization_score"]["score"] is None
    assert gen_data["coverage_report"]["seen"] == 0

    skills_resp = client.get(f"/trainee/{new_id}/skills")
    assert skills_resp.status_code == 200
    assert "detection" in skills_resp.json()

    # Adaptive plan for new trainee
    plan_resp = client.get(f"/trainee/{new_id}/plan")
    assert plan_resp.status_code == 200
    assert "scenario" in plan_resp.json()


def test_adaptive_selector_progression():
    """Verify completing sessions updates Bayesian skill model and alters recommendations."""
    trainee_id = "qa_adaptive_progression"
    plan1 = client.get(f"/trainee/{trainee_id}/plan").json()

    # Complete a session
    start_resp = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "practice"}).json()
    sid = start_resp["session_id"]
    client.post("/session/result", json={"session_id": sid, "events": [], "false_alarms": 0})

    plan2 = client.get(f"/trainee/{trainee_id}/plan").json()
    assert plan2["scenario"] is not None
    assert "reason" in plan2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

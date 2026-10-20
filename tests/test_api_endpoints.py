"""Unit tests for DroneDrill AI Extended Endpoints.

Tests:
1. POST /session/next creates an adaptive practice session.
2. GET /trainee/{id}/skills returns the full skill matrix.
3. GET /trainee/{id}/performance returns session history.
4. GET /trainee/{id}/generalization returns score, rote indicator, and coverage.
5. GET /trainee/{id}/plan previews next recommendation without creating a session.
6. POST /session/start supports mode='test' from held-out cells and mode='practice'.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.factors import HELD_OUT_CELLS, PRACTICE_CELLS
from app.db import get_trainee_sessions


@pytest.fixture
def client():
    return TestClient(app)


def test_session_start_modes(client):
    """Verify POST /session/start supports practice and test modes."""
    # Test mode
    res_test = client.post("/session/start", json={"trainee_id": "api_eval_test", "mode": "test"})
    assert res_test.status_code == 200
    data_test = res_test.json()
    assert data_test["mode"] == "test"
    assert tuple(data_test["cell"]) in HELD_OUT_CELLS

    # Practice mode
    res_prac = client.post("/session/start", json={"trainee_id": "api_eval_prac", "mode": "practice"})
    assert res_prac.status_code == 200
    data_prac = res_prac.json()
    assert data_prac["mode"] == "practice"
    assert tuple(data_prac["cell"]) in PRACTICE_CELLS


import uuid

def test_session_next_and_plan(client):
    """Verify POST /session/next creates a session and GET /trainee/{id}/plan previews recommendation."""
    trainee_id = f"trainee_api_next_{uuid.uuid4().hex[:8]}"

    # Plan preview does not create a session
    plan_resp = client.get(f"/trainee/{trainee_id}/plan")
    assert plan_resp.status_code == 200
    plan_data = plan_resp.json()
    assert "scenario" in plan_data
    assert "reason" in plan_data

    sessions_before = get_trainee_sessions(trainee_id)
    assert len(sessions_before) == 0

    # /session/next creates a session
    next_resp = client.post("/session/next", json={"trainee_id": trainee_id})
    assert next_resp.status_code == 200
    next_data = next_resp.json()
    assert "session_id" in next_data
    assert "scenario" in next_data
    assert "reason" in next_data
    assert next_data["mode"] == "practice"

    sessions_after = get_trainee_sessions(trainee_id)
    assert len(sessions_after) == 1


def test_trainee_endpoints(client):
    """Verify /trainee/{id}/skills, /trainee/{id}/performance, and /trainee/{id}/generalization."""
    trainee_id = f"trainee_api_full_{uuid.uuid4().hex[:8]}"

    # Start and score a session
    start_resp = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "practice"})
    assert start_resp.status_code == 200
    sess_id = start_resp.json()["session_id"]

    result_resp = client.post(
        "/session/result",
        json={
            "session_id": sess_id,
            "events": [],
            "false_alarms": 0,
        },
    )
    assert result_resp.status_code == 200

    # Skills endpoint
    skills_resp = client.get(f"/trainee/{trainee_id}/skills")
    assert skills_resp.status_code == 200
    skills_data = skills_resp.json()
    assert "classification" in skills_data
    assert "detection" in skills_data

    # Performance endpoint
    perf_resp = client.get(f"/trainee/{trainee_id}/performance")
    assert perf_resp.status_code == 200
    perf_data = perf_resp.json()
    assert len(perf_data["sessions"]) >= 1
    first_sess = perf_data["sessions"][0]
    assert "session_id" in first_sess
    assert "per_skill_scores" in first_sess

    # Generalization endpoint
    gen_resp = client.get(f"/trainee/{trainee_id}/generalization")
    assert gen_resp.status_code == 200
    gen_data = gen_resp.json()
    assert "generalization_score" in gen_data
    assert "rote_indicator" in gen_data
    assert "coverage_report" in gen_data


def test_static_app_serving(client):
    """Verify Landing page and Simulator screen HTML and assets are served from /app."""
    resp = client.get("/app/")
    assert resp.status_code == 200
    content = resp.text
    assert "DroneDrill AI" in content
    assert "START SIMULATION" in content

    sim_resp = client.get("/app/simulator.html")
    assert sim_resp.status_code == 200
    sim_content = sim_resp.text
    assert "DroneDrill AI" in sim_content
    assert "main-canvas" in sim_content
    assert "radar-widget-canvas" in sim_content
    assert "Your Assessment" in sim_content

    # Check asset serving
    css_resp = client.get("/app/style.css")
    assert css_resp.status_code == 200
    assert "--bg" in css_resp.text or "--blue" in css_resp.text

    cfg_resp = client.get("/app/config.js")
    assert cfg_resp.status_code == 200
    assert "CONFIG" in cfg_resp.text

    app_js_resp = client.get("/app/app.js")
    assert app_js_resp.status_code == 200
    assert "CanvasRenderer" in app_js_resp.text

    # Skills page and logic
    skills_resp = client.get("/app/skills.html")
    assert skills_resp.status_code == 200
    assert "Bayesian Skill Proficiency Heatmap" in skills_resp.text

    skills_js_resp = client.get("/app/skills.js")
    assert skills_js_resp.status_code == 200
    assert "loadSkillsMatrix" in skills_js_resp.text

    # AAR page and logic
    aar_resp = client.get("/app/aar.html")
    assert aar_resp.status_code == 200
    assert "Target Engagement Multi-Lane Timeline" in aar_resp.text

    aar_js_resp = client.get("/app/aar.js")
    assert aar_js_resp.status_code == 200
    assert "renderTimelineSVG" in aar_js_resp.text

    # Instructor page and logic
    inst_resp = client.get("/app/instructor.html")
    assert inst_resp.status_code == 200
    assert "Unit Trainee Roster" in inst_resp.text

    inst_js_resp = client.get("/app/instructor.js")
    assert inst_js_resp.status_code == 200
    assert "loadDecisionTreeRules" in inst_js_resp.text

    # Chart vendor utility
    chart_util_resp = client.get("/app/vendor/chart_util.js")
    assert chart_util_resp.status_code == 200
    assert "SimpleChart" in chart_util_resp.text


"""DroneDrill AI - Backend API (FastAPI).

Provides core endpoints for training session lifecycle, adaptive recommendation,
Bayesian skill matrices, generalization evaluation, simulated telemetry streams,
and After Action Review (AAR) analysis.
Runs offline with SQLite and local scenario generation.
Never claims real MAVLink hardware support: uses MAVLink-style telemetry packets.
"""

import json
import os
import random
import uuid
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import numpy as np
from pydantic import BaseModel, Field

from app.db import (
    init_db,
    record_session,
    record_cell_seen,
    record_fingerprint,
    record_event,
    get_events,
    get_session,
    update_session_score,
    has_trainee_seen_fingerprint,
    get_trainee_sessions,
    get_all_trainees,
    get_connection,
)
from app.factors import init_split, HELD_OUT_CELLS, PRACTICE_CELLS, OBJECT_COUNT_LEVELS
from app.generator import generate_scenario, generate_for_cell, coverage_report
from app.scoring import score_session, load_decision_tree
from app.skill_model import update_from_result, skill_matrix
from app.selector import select_next
from app.generalization import generalization_score, rote_indicator
from app.telemetry import SimulatedSource, TelemetryAdapter
from app.recorder import record_telemetry, get_telemetry
from app.sensor_view import visibility_windows, get_scored_and_unscored_objects
from app.scripted import (
    load_scripted_scenarios,
    get_scripted_scenario,
    list_scripted_library,
)

# Initialize database schema, condition split, and scripted library
init_db()
init_split()
load_scripted_scenarios()

BASE_DIR = Path(__file__).resolve().parent.parent
ERROR_LOG_PATH = BASE_DIR / "data" / "errors.log"

app = FastAPI(
    title="DroneDrill AI Core",
    description="Offline AI-enabled drone/counter-drone threat simulation trainer API",
    version="1.0.0",
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler for dev environment.
    
    Logs full traceback to console and to data/errors.log,
    and returns JSON {"error": "<short message>", "where": "<function>"} with status 500.
    """
    tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    print(f"[DroneDrill AI ERROR] Exception during {request.method} {request.url.path}:\n{tb_str}", file=sys.stderr)

    try:
        ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(ERROR_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"--- Error at {request.method} {request.url.path} ---\n{tb_str}\n\n")
    except Exception as log_err:
        print(f"[DroneDrill AI ERROR] Failed writing to errors.log: {log_err}", file=sys.stderr)

    where = "unknown"
    tb = exc.__traceback__
    while tb:
        where = tb.tb_frame.f_code.co_name
        tb = tb.tb_next

    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "where": where},
    )

# CORS enabled for localhost (various ports) and Render deployment
_cors_origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://localhost:8080",
    "http://127.0.0.1",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8080",
]
_render_url = os.environ.get("RENDER_EXTERNAL_URL")
if _render_url:
    _cors_origins.append(_render_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CLIENT_DIR = BASE_DIR / "client"
CLIENT_DIR.mkdir(parents=True, exist_ok=True)

@app.middleware("http")
async def add_no_cache_header(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/app"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

app.mount("/app", StaticFiles(directory=str(CLIENT_DIR), html=True), name="client")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Redirect root to client UI."""
    return RedirectResponse(url="/app/")


class SessionStartRequest(BaseModel):
    """Payload to start a training session."""
    trainee_id: str = Field(..., description="Unique identifier for the trainee")
    mode: str = Field("practice", description="Session mode: practice or test")
    scripted_id: Optional[str] = Field(None, description="Optional hand-authored scripted scenario ID")
    constraints: Optional[Dict[str, Any]] = Field(None, description="Optional instructor factor constraints")


class SessionNextRequest(BaseModel):
    """Payload to request the next adaptive practice session."""
    trainee_id: str = Field(..., description="Unique identifier for the trainee")


class SessionResultRequest(BaseModel):
    """Payload to submit trainee events and evaluate a completed session."""
    session_id: str = Field(..., min_length=1, description="Active session ID to evaluate")
    events: List[Any] = Field(default_factory=list, description="List of object interaction events")
    false_alarms: int = Field(0, ge=0, description="Number of false alarms triggered")


@app.get("/health")
def health() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/scenarios")
def get_scenario_library() -> Dict[str, Any]:
    """Retrieve list of hand-authored scripted scenarios in the training library."""
    scenarios = list_scripted_library()
    return {
        "scenarios": scenarios,
        "total": len(scenarios),
        "note": "Procedural scenarios are generated dynamically by the generator engine upon session creation.",
    }


@app.post("/session/start")
def start_session(request: SessionStartRequest) -> Dict[str, Any]:
    """Start a simulation session for a trainee.
    
    Generates a scenario (practice cells for 'practice', held-out cells for 'test'),
    records the session and cell visit, stores MAVLink-style telemetry packets,
    detects repeated fingerprints, and returns full session details.
    """
    if not request.trainee_id.strip():
        raise HTTPException(status_code=400, detail="trainee_id cannot be empty")

    trainee_id = request.trainee_id.strip()
    session_mode = request.mode.strip().lower() if request.mode else "practice"
    if session_mode not in ("practice", "test"):
        raise HTTPException(status_code=400, detail="Invalid session mode. Must be 'practice' or 'test'")

    session_id = str(uuid.uuid4())

    # 1. Scripted scenario launch
    if request.scripted_id:
        if session_mode != "practice":
            raise HTTPException(status_code=400, detail="Scripted scenarios are only available in practice mode")
        scripted_scen = get_scripted_scenario(request.scripted_id)
        if not scripted_scen:
            raise HTTPException(status_code=404, detail=f"Scripted scenario '{request.scripted_id}' not found")
        scenario = dict(scripted_scen)
        scenario["source"] = "scripted"

    # 2. Instructor launcher with pinned constraints
    elif request.constraints:
        if session_mode != "practice":
            raise HTTPException(status_code=400, detail="Instructor constraints are only available in practice mode")

        factor_indices = {
            "time_of_day": 0,
            "weather": 1,
            "terrain": 2,
            "sensor_mode": 3,
            "degradation": 4,
            "distractors": 5,
        }

        matching_cells = []
        for cell in sorted(list(PRACTICE_CELLS)):
            matches = True
            for f_name, idx in factor_indices.items():
                if f_name in request.constraints:
                    if cell[idx] != request.constraints[f_name]:
                        matches = False
                        break
            if matches:
                matching_cells.append(cell)

        if not matching_cells:
            raise HTTPException(
                status_code=400,
                detail=f"No practice cell matches the provided constraints: {request.constraints}",
            )

        obj_count_req = request.constraints.get("object_count")
        if obj_count_req and obj_count_req not in OBJECT_COUNT_LEVELS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid object_count constraint: '{obj_count_req}'. Must be one of {OBJECT_COUNT_LEVELS}",
            )

        chosen_cell = random.choice(matching_cells)
        scenario = generate_for_cell(chosen_cell, object_count=obj_count_req)
        scenario["source"] = "instructor_launched"

    # 3. Standard test or practice procedural scenario
    elif session_mode == "test":
        candidate_cells = sorted(list(HELD_OUT_CELLS))
        chosen_cell = random.choice(candidate_cells)
        scenario = generate_for_cell(chosen_cell)
    else:
        scenario = generate_scenario(allow_held_out=False)

    fp = scenario["fingerprint"]
    is_repeat = 1 if has_trainee_seen_fingerprint(trainee_id, fp) else 0

    # Persist session record
    record_session(
        session_id=session_id,
        trainee_id=trainee_id,
        scenario_id=scenario["scenario_id"],
        cell=scenario["cell"],
        difficulty_index=scenario["difficulty_index"],
        scenario_json=scenario,
        mode=session_mode,
        is_repeat=is_repeat,
        fingerprint=fp,
    )
    record_cell_seen(
        trainee_id=trainee_id,
        cell=scenario["cell"],
    )

    # Store scenario fingerprint
    record_fingerprint(
        fingerprint=fp,
        scenario_id=scenario["scenario_id"],
    )

    # Ingest and store 5 Hz MAVLink-style simulated telemetry stream
    raw_pkts = SimulatedSource().packets(scenario)
    processed = TelemetryAdapter.process(raw_pkts)
    record_telemetry(session_id, processed["packets"])

    return {
        "session_id": session_id,
        "fingerprint": fp,
        "scenario_id": scenario["scenario_id"],
        "cell": scenario["cell"],
        "factors": scenario["factors"],
        "objects": scenario["objects"],
        "duration_s": scenario["duration_s"],
        "noise_windows": scenario.get("noise_windows", 3),
        "difficulty_index": scenario["difficulty_index"],
        "scenario": scenario,
        "mode": session_mode,
        "is_repeat": is_repeat,
    }


@app.post("/session/next")
def next_session(request: SessionNextRequest) -> Dict[str, Any]:
    """Create an adaptive practice session using the Bayesian selector.
    
    Selects the next practice scenario based on trainee weaknesses, creates a session record,
    stores processed telemetry packets, and returns the scenario with the selection reason.
    """
    if not request.trainee_id.strip():
        raise HTTPException(status_code=400, detail="trainee_id cannot be empty")

    trainee_id = request.trainee_id.strip()
    selection = select_next(trainee_id)
    scenario = selection["scenario"]
    reason = selection["reason"]
    session_id = str(uuid.uuid4())

    fp = scenario["fingerprint"]
    is_repeat = 1 if has_trainee_seen_fingerprint(trainee_id, fp) else 0

    record_session(
        session_id=session_id,
        trainee_id=trainee_id,
        scenario_id=scenario["scenario_id"],
        cell=scenario["cell"],
        difficulty_index=scenario["difficulty_index"],
        scenario_json=scenario,
        mode="practice",
        is_repeat=is_repeat,
        fingerprint=fp,
    )
    record_cell_seen(
        trainee_id=trainee_id,
        cell=scenario["cell"],
    )
    record_fingerprint(
        fingerprint=fp,
        scenario_id=scenario["scenario_id"],
    )

    # Ingest and store 5 Hz MAVLink-style simulated telemetry stream
    raw_pkts = SimulatedSource().packets(scenario)
    processed = TelemetryAdapter.process(raw_pkts)
    record_telemetry(session_id, processed["packets"])

    return {
        "session_id": session_id,
        "scenario": scenario,
        "reason": reason,
        "mode": "practice",
        "is_repeat": is_repeat,
    }


@app.post("/session/result")
def submit_session_result(request: SessionResultRequest) -> Dict[str, Any]:
    """Evaluate trainee performance and store results for the completed session.
    
    Stores individual events with sim-time t_s.
    Updates the Bayesian skill model for practice sessions only.
    Test sessions feed the Generalization Score.
    """
    # 1. Temporary debug log of incoming payload (truncated to 2000 chars)
    try:
        body_dump = str(request.model_dump())
        print(f"[DEBUG /session/result] Incoming payload: {body_dump[:2000]}")
    except Exception as dbg_err:
        print(f"[DEBUG /session/result] Payload log error: {dbg_err}")

    session_id = request.session_id.strip() if request.session_id else ""
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id cannot be empty")
    if request.false_alarms < 0:
        raise HTTPException(status_code=422, detail="false_alarms must be non-negative")

    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Double submission: return 409 with clear message, not 500
    if session.get("overall_score") is not None or session.get("scores") is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Session '{session_id}' has already been evaluated and submitted.",
        )

    scenario = session.get("scenario")
    if not scenario:
        raise HTTPException(status_code=400, detail="Scenario data not found for session")

    # Canonical label mapping helpers
    class_label_map = {
        "multirotor drone": "multirotor",
        "multirotor": "multirotor",
        "fixed-wing uav": "fixed_wing_uav",
        "fixed wing uav": "fixed_wing_uav",
        "fixed_wing": "fixed_wing_uav",
        "fixed_wing_uav": "fixed_wing_uav",
        "bird": "bird",
        "balloon": "balloon",
        "aircraft": "light_aircraft",
        "light aircraft": "light_aircraft",
        "light_aircraft": "light_aircraft",
        "unknown": "unknown",
    }
    threat_label_map = {
        "benign": 0,
        "low": 1,
        "elevated": 2,
        "high": 3,
        0: 0,
        1: 1,
        2: 2,
        3: 3,
        "0": 0,
        "1": 1,
        "2": 2,
        "3": 3,
    }
    response_label_map = {
        "ignore contact": "ignore",
        "ignore": "ignore",
        "log only": "log_only",
        "log_only": "log_only",
        "monitor track": "monitor",
        "monitor": "monitor",
        "report to command": "report_to_command",
        "report_to_command": "report_to_command",
        "alert unit": "alert_unit",
        "alert_unit": "alert_unit",
        "countermeasure (simulated)": "countermeasure_simulated",
        "countermeasure simulated": "countermeasure_simulated",
        "countermeasure": "countermeasure_simulated",
        "countermeasure_simulated": "countermeasure_simulated",
    }

    # Store individual interaction events in events table with simulation time t_s
    valid_events: List[Dict[str, Any]] = []
    for ev in request.events:
        if not isinstance(ev, dict):
            continue
        cleaned_ev = dict(ev)

        # Sanitize class label
        raw_cls = cleaned_ev.get("classified_as")
        if raw_cls is not None:
            cls_str = str(raw_cls).strip().lower()
            cleaned_ev["classified_as"] = class_label_map.get(cls_str, cls_str) if cls_str else None

        # Sanitize threat label
        raw_threat = cleaned_ev.get("threat_level_rated")
        if raw_threat is not None:
            threat_str = str(raw_threat).strip().lower()
            mapped_threat = threat_label_map.get(threat_str, None)
            if mapped_threat is None:
                try:
                    mapped_threat = int(raw_threat)
                except (ValueError, TypeError):
                    mapped_threat = None
            cleaned_ev["threat_level_rated"] = mapped_threat

        # Sanitize response choice
        raw_resp = cleaned_ev.get("response_chosen")
        if raw_resp is not None:
            resp_str = str(raw_resp).strip().lower()
            cleaned_ev["response_chosen"] = response_label_map.get(resp_str, resp_str) if resp_str else None

        # Sanitize confidence
        raw_conf = cleaned_ev.get("confidence")
        if raw_conf is not None:
            try:
                c = float(raw_conf)
                if not np.isfinite(c):
                    cleaned_ev["confidence"] = 0.5
                elif c > 1.0 and c <= 100.0:
                    cleaned_ev["confidence"] = c / 100.0
                else:
                    cleaned_ev["confidence"] = float(np.clip(c, 0.0, 1.0))
            except (ValueError, TypeError):
                cleaned_ev["confidence"] = None

        raw_t = cleaned_ev.get("detect_time_s") if cleaned_ev.get("detect_time_s") is not None else cleaned_ev.get("t_s")
        try:
            t_s = float(raw_t) if raw_t is not None else 0.0
            if not np.isfinite(t_s) or t_s < 0:
                t_s = 0.0
        except (ValueError, TypeError):
            t_s = 0.0

        cleaned_ev["t_s"] = t_s
        valid_events.append(cleaned_ev)

        record_event(
            session_id=session_id,
            event_type="object_assessment",
            payload=cleaned_ev,
            t_s=t_s,
        )

    if request.false_alarms > 0:
        try:
            dur_s = float(scenario.get("duration_s", 60.0))
            if not np.isfinite(dur_s) or dur_s < 0:
                dur_s = 60.0
        except (ValueError, TypeError):
            dur_s = 60.0

        record_event(
            session_id=session_id,
            event_type="false_alarm_count",
            payload={"count": request.false_alarms},
            t_s=dur_s,
        )

    # Calculate multi-dimensional score
    scores = score_session(
        scenario=scenario,
        events=valid_events,
        false_alarms=request.false_alarms,
    )

    # Persist overall score and detailed scores to session record
    update_session_score(session_id, scores["overall"], scores_dict=scores)

    # Bayesian skill model updates on practice sessions only
    session_mode = session.get("mode", "practice")
    if session_mode == "practice":
        update_from_result(session["trainee_id"], scores["skill_scores"])

    return scores


@app.get("/scenario/{session_id}/telemetry")
def get_scenario_telemetry(session_id: str) -> Dict[str, Any]:
    """Retrieve processed MAVLink-style telemetry and sensor visibility windows.
    
    Includes object appearance for silhouette rendering in prototype UI.
    Trainee interface never exposes true labels.
    """
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    scenario = session.get("scenario")
    if not scenario:
        raise HTTPException(status_code=400, detail="Scenario data not found")

    # Fetch stored flight data from DB; fallback to generating if not yet stored
    stored_pkts = get_telemetry(session_id)
    if stored_pkts:
        processed_packets = stored_pkts
        stats = {
            "total_received": len(stored_pkts),
            "valid_count": len(stored_pkts),
            "dropped_count": 0,
            "drop_reasons": {},
        }
    else:
        raw_pkts = SimulatedSource().packets(scenario)
        adapter_res = TelemetryAdapter.process(raw_pkts)
        processed_packets = [p.model_dump() for p in adapter_res["packets"]]
        stats = adapter_res["stats"]
        record_telemetry(session_id, adapter_res["packets"])

    vis_windows = visibility_windows(scenario)

    # Prototype trade-off: appearance is included so client UI can render target silhouettes.
    # The actual trainee user interface never displays true ground-truth labels during drills.
    object_appearances = [
        {
            "id": obj["id"],
            "appearance": obj.get("true_class", "unknown"),
        }
        for obj in scenario.get("objects", [])
    ]

    return {
        "session_id": session_id,
        "source": "simulated",
        "packets": processed_packets,
        "visibility_windows": vis_windows,
        "adapter_stats": stats,
        "objects": object_appearances,
    }


@app.get("/aar/{session_id}")
def get_after_action_review(session_id: str) -> Dict[str, Any]:
    """Retrieve comprehensive After Action Review (AAR) timeline and diagnostic feedback.
    
    Merges ground truth, sensor visibility windows, trainee actions, error taxonomy,
    calibration note, and rule-based pedagogical feedback sentences.
    """
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    scenario = session.get("scenario")
    if not scenario:
        raise HTTPException(status_code=400, detail="Scenario data not found")

    scores = session.get("scores") or {}
    objects = scenario.get("objects", [])
    tree_data = load_decision_tree()
    rules = tree_data.get("rules", {})

    # Trainee recorded events from events table
    raw_events = get_events(session_id)
    trainee_events_by_id: Dict[str, Dict[str, Any]] = {}
    false_alarm_count = 0

    for ev_row in raw_events:
        ev_type = ev_row.get("event_type")
        payload = ev_row.get("payload_data") or {}
        if ev_type == "object_assessment":
            obj_id = payload.get("object_id")
            if obj_id and obj_id not in trainee_events_by_id:
                trainee_events_by_id[obj_id] = payload
        elif ev_type == "false_alarm_count":
            false_alarm_count += int(payload.get("count", 0))

    vis_windows = visibility_windows(scenario)
    scored_objects, not_scored_ids = get_scored_and_unscored_objects(scenario, min_visible_s=3.0)
    scored_id_set = {str(obj["id"]) for obj in scored_objects}

    # 1. Timeline & Ground Truth compilation
    timeline = []
    errors = {
        "missed": [],
        "misclassifications": [],
        "wrong_threat_levels": [],
        "suboptimal_responses": [],
        "false_alarms": false_alarm_count,
    }

    ground_truth = []
    trainee_actions = []

    confidences = []
    correctness_flags = []

    for obj in objects:
        oid = str(obj["id"])
        true_cls = obj.get("true_class", "unknown")
        beh = obj.get("behaviour_label", "benign")
        true_threat = obj.get("true_threat_level", 1)
        appears_at = obj.get("appears_at_time", 0.0)

        rule_key = f"{true_cls}|{beh}"
        rule = rules.get(rule_key, {})
        expected_threat = rule.get("expected_threat_level", true_threat)
        responses = rule.get("responses", {})
        best_response = max(responses.items(), key=lambda x: x[1])[0] if responses else "monitor"

        gt_item = {
            "object_id": oid,
            "appears_at_time": appears_at,
            "true_class": true_cls,
            "true_threat_level": true_threat,
            "behaviour_label": beh,
            "expected_response": best_response,
        }
        ground_truth.append(gt_item)

        trainee_ev = trainee_events_by_id.get(oid)
        if not trainee_ev or not trainee_ev.get("detected", False):
            if oid in scored_id_set:
                errors["missed"].append(oid)
            trainee_act = {
                "object_id": oid,
                "detected": False,
                "detect_time_s": None,
                "classified_as": None,
                "threat_level_rated": None,
                "response_chosen": None,
                "confidence": None,
            }
        else:
            pred_cls = str(trainee_ev.get("classified_as") or "unknown")
            rated_threat = trainee_ev.get("threat_level_rated")
            resp_chosen = str(trainee_ev.get("response_chosen") or "")
            try:
                raw_conf = trainee_ev.get("confidence")
                conf = float(raw_conf) if raw_conf is not None else 0.5
                if not np.isfinite(conf):
                    conf = 0.5
                elif conf > 1.0 and conf <= 100.0:
                    conf = conf / 100.0
                conf = float(np.clip(conf, 0.0, 1.0))
            except (ValueError, TypeError):
                conf = 0.5

            try:
                raw_dt = trainee_ev.get("detect_time_s")
                detect_time = float(raw_dt) if raw_dt is not None else 0.0
                if not np.isfinite(detect_time) or detect_time < 0:
                    detect_time = 0.0
            except (ValueError, TypeError):
                detect_time = 0.0

            is_correct_cls = (pred_cls == true_cls)
            confidences.append(conf)
            correctness_flags.append(is_correct_cls)

            if not is_correct_cls:
                errors["misclassifications"].append(
                    {
                        "object_id": oid,
                        "true_class": true_cls,
                        "classified_as": pred_cls,
                        "confusion_pair": f"{true_cls}->{pred_cls}",
                    }
                )

            if rated_threat != expected_threat:
                errors["wrong_threat_levels"].append(
                    {
                        "object_id": oid,
                        "expected_level": expected_threat,
                        "rated_level": rated_threat,
                    }
                )

            if resp_chosen != best_response:
                errors["suboptimal_responses"].append(
                    {
                        "object_id": oid,
                        "chosen_response": resp_chosen,
                        "expected_response": best_response,
                    }
                )

            trainee_act = {
                "object_id": oid,
                "detected": True,
                "detect_time_s": detect_time,
                "classified_as": pred_cls,
                "threat_level_rated": rated_threat,
                "response_chosen": resp_chosen,
                "confidence": conf,
            }

        trainee_actions.append(trainee_act)

        timeline.append(
            {
                "object_id": oid,
                "ground_truth": gt_item,
                "sensor_visibility": vis_windows.get(oid, []),
                "trainee_action": trainee_act,
            }
        )

    # 2. Confidence vs Correctness Note
    if confidences:
        high_conf_wrongs = sum(1 for c, ok in zip(confidences, correctness_flags) if c >= 0.8 and not ok)
        hedged_rights = sum(1 for c, ok in zip(confidences, correctness_flags) if c <= 0.6 and ok)
        mean_conf = float(np.mean(confidences))
        acc = float(np.mean(correctness_flags))

        if high_conf_wrongs > 0:
            cal_note = f"Warning: Overconfidence detected ({high_conf_wrongs} incorrect identification(s) rated with >=80% confidence)."
        elif hedged_rights > 0:
            cal_note = f"Notice: Hesitant under-confidence ({hedged_rights} correct identification(s) had low <=60% confidence)."
        elif abs(mean_conf - acc) <= 0.15:
            cal_note = f"Well-calibrated: Confidence ({mean_conf*100:.0f}%) accurately matches classification accuracy ({acc*100:.0f}%)."
        else:
            cal_note = f"Moderate calibration alignment: Mean confidence {mean_conf*100:.0f}%, accuracy {acc*100:.0f}%."
    else:
        cal_note = "No objects detected to evaluate confidence calibration."

    # 3. Rule-based Feedback Sentences
    feedback_sentences = []
    weather = scenario.get("factors", {}).get("weather", "clear")
    time_of_day = scenario.get("factors", {}).get("time_of_day", "day")
    degradation = scenario.get("factors", {}).get("degradation", "none")

    deg_str = "no sensor degradation" if degradation == "none" else f"{degradation} sensor degradation"

    if errors["missed"]:
        n_miss = len(errors["missed"])
        n_scored = len(scored_objects)
        feedback_sentences.append(
            f"{n_miss} of {n_scored} target(s) were missed entirely under {time_of_day}, {weather} and {deg_str}."
        )

    if errors["misclassifications"]:
        for mis in errors["misclassifications"]:
            feedback_sentences.append(
                f"Object {mis['object_id']} ({mis['true_class']}) was misclassified as {mis['classified_as']}."
            )

    if errors["wrong_threat_levels"]:
        feedback_sentences.append(
            f"{len(errors['wrong_threat_levels'])} target(s) had incorrect threat priority ratings."
        )

    if errors["suboptimal_responses"]:
        feedback_sentences.append(
            f"{len(errors['suboptimal_responses'])} target(s) received non-standard response choices according to the decision rules."
        )

    if false_alarm_count > 0:
        feedback_sentences.append(
            f"{false_alarm_count} false alarm(s) logged in non-target airspace windows."
        )

    if not feedback_sentences:
        feedback_sentences.append("Exemplary performance: Zero detection, classification, or procedural errors.")

    # Look for previous completed session for the trainee
    trainee_sessions = get_trainee_sessions(session["trainee_id"])
    prev_session = None
    for idx_s, s in enumerate(trainee_sessions):
        if s.get("session_id") == session_id:
            if idx_s > 0:
                prev_session = trainee_sessions[idx_s - 1]
            break

    scores_data = session.get("scores") or {}
    prev_scores_data = (prev_session.get("scores") or {}) if prev_session else {}
    deltas = {}
    for skill_name in ["overall", "detection", "classification", "decision", "timeliness", "calibration"]:
        cur_v = scores_data.get(f"{skill_name}_score") if skill_name != "overall" else scores_data.get("overall", session.get("overall_score"))
        prv_v = prev_scores_data.get(f"{skill_name}_score") if skill_name != "overall" else prev_scores_data.get("overall", prev_session.get("overall_score") if prev_session else None)
        if cur_v is not None and prv_v is not None:
            deltas[skill_name] = round((float(cur_v) - float(prv_v)) * 100, 1)
        else:
            deltas[skill_name] = None

    return {
        "session_id": session_id,
        "trainee_id": session["trainee_id"],
        "scenario_id": scenario["scenario_id"],
        "scenario_title": scenario.get("title") or scenario.get("scenario_id", ""),
        "mode": session.get("mode", "practice"),
        "date": session.get("started_at"),
        "difficulty_index": scenario.get("difficulty_index", session.get("difficulty_index", 0.5)),
        "factors": scenario.get("factors") or {},
        "overall_score": session.get("overall_score"),
        "scores": scores_data,
        "deltas": deltas,
        "previous_scores": prev_scores_data,
        "ground_truth": ground_truth,
        "sensor_view": vis_windows,
        "visibility_windows": vis_windows,
        "not_scored": not_scored_ids,
        "scored_objects": [obj["id"] for obj in scored_objects],
        "trainee_actions": trainee_actions,
        "timeline": timeline,
        "errors": errors,
        "confidence_vs_correctness": cal_note,
        "feedback_sentences": feedback_sentences,
    }


@app.get("/trainee/{id}/skills")
def get_trainee_skills(id: str) -> Dict[str, Any]:
    """Retrieve the full hierarchical Bayesian skill matrix for a trainee."""
    trainee_id = id.strip()
    if not trainee_id:
        raise HTTPException(status_code=400, detail="Trainee ID cannot be empty")
    return skill_matrix(trainee_id)


@app.get("/trainee/{id}/performance")
def get_trainee_performance(id: str) -> Dict[str, Any]:
    """Retrieve historical sessions performance records for a trainee."""
    trainee_id = id.strip()
    if not trainee_id:
        raise HTTPException(status_code=400, detail="Trainee ID cannot be empty")

    sessions = get_trainee_sessions(trainee_id)
    session_list = []
    for s in sessions:
        scores = s.get("scores") or {}
        per_skill_scores = {
            "detection": scores.get("detection_score"),
            "classification": scores.get("classification_score"),
            "decision": scores.get("decision_score"),
            "timeliness": scores.get("timeliness_score"),
            "calibration": scores.get("calibration_score"),
        }
        session_list.append(
            {
                "session_id": s["session_id"],
                "date": s["started_at"],
                "mode": s.get("mode", "practice"),
                "overall": s.get("overall_score"),
                "difficulty_index": s.get("difficulty_index"),
                "per_skill_scores": per_skill_scores,
            }
        )

    return {"trainee_id": trainee_id, "sessions": session_list}


@app.get("/trainee/{id}/generalization")
def get_trainee_generalization(id: str) -> Dict[str, Any]:
    """Retrieve Generalization Score, Rote Indicator, and Cell Coverage report for a trainee."""
    trainee_id = id.strip()
    if not trainee_id:
        raise HTTPException(status_code=400, detail="Trainee ID cannot be empty")

    gen = generalization_score(trainee_id)
    rote = rote_indicator(trainee_id)
    cov = coverage_report(trainee_id)

    return {
        "trainee_id": trainee_id,
        "generalization_score": gen,
        "rote_indicator": rote,
        "coverage_report": {
            "coverage": float(cov),
            "seen": cov.seen,
            "total": cov.total,
        },
    }


@app.get("/trainee/{id}/plan")
def get_trainee_plan(id: str) -> Dict[str, Any]:
    """Preview next adaptive scenario recommendation without creating a session in the database."""
    trainee_id = id.strip()
    if not trainee_id:
        raise HTTPException(status_code=400, detail="Trainee ID cannot be empty")

    selection = select_next(trainee_id)
    return {
        "trainee_id": trainee_id,
        "scenario": selection["scenario"],
        "reason": selection["reason"],
    }


# --- Instructor Dashboard & Cohort Endpoints ---

@app.get("/trainees")
def get_all_trainees_summary() -> List[Dict[str, Any]]:
    """Retrieve instructor view of all trainees with performance, generalization, and rote gap metrics."""
    trainees = get_all_trainees()
    result = []
    for t in trainees:
        tid = t["id"]
        sessions = get_trainee_sessions(tid)
        scored = [s for s in sessions if s.get("overall_score") is not None]
        mean_ovr = round(float(np.mean([s["overall_score"] for s in scored])), 3) if scored else None

        gen = generalization_score(tid)
        rote = rote_indicator(tid)

        result.append(
            {
                "id": tid,
                "name": t.get("name") or tid,
                "is_demo": int(t.get("is_demo") or 0),
                "sessions": len(scored),
                "mean_overall": mean_ovr,
                "generalization_score": gen.get("score"),
                "rote_gap": rote.get("gap"),
            }
        )
    return result


@app.get("/unit/summary")
def get_unit_summary() -> Dict[str, Any]:
    """Retrieve aggregated cohort analytics across the training unit."""
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Score distribution across all evaluated sessions
    cursor.execute("SELECT overall_score FROM sessions WHERE overall_score IS NOT NULL;")
    scores = [float(r["overall_score"]) for r in cursor.fetchall()]

    score_dist = {
        "0.0-0.2": 0,
        "0.2-0.4": 0,
        "0.4-0.6": 0,
        "0.6-0.8": 0,
        "0.8-1.0": 0,
        "total_sessions": len(scores),
        "unit_mean": round(float(np.mean(scores)), 3) if scores else None,
    }
    for s in scores:
        if s < 0.2:
            score_dist["0.0-0.2"] += 1
        elif s < 0.4:
            score_dist["0.2-0.4"] += 1
        elif s < 0.6:
            score_dist["0.4-0.6"] += 1
        elif s < 0.8:
            score_dist["0.6-0.8"] += 1
        else:
            score_dist["0.8-1.0"] += 1

    # 2. Top confusion pairs across the unit
    cursor.execute("SELECT session_id, scenario_json FROM sessions WHERE scenario_json IS NOT NULL;")
    scenario_classes: Dict[str, Dict[str, str]] = {}
    for r in cursor.fetchall():
        sid = r["session_id"]
        try:
            scen_data = json.loads(r["scenario_json"])
            scenario_classes[sid] = {
                obj["id"]: obj.get("true_class", "unknown")
                for obj in scen_data.get("objects", [])
            }
        except Exception:
            continue

    cursor.execute("SELECT session_id, payload FROM events WHERE event_type = 'object_assessment';")
    event_rows = cursor.fetchall()

    confusion_counts: Dict[str, int] = {}
    for er in event_rows:
        sid = er["session_id"]
        try:
            p = json.loads(er["payload"]) if er["payload"] else {}
        except Exception:
            continue
        oid = p.get("object_id")
        pred_cls = p.get("classified_as")
        true_cls = p.get("true_class") or scenario_classes.get(sid, {}).get(oid)

        if true_cls and pred_cls and true_cls != pred_cls:
            pair = f"{true_cls}->{pred_cls}"
            confusion_counts[pair] = confusion_counts.get(pair, 0) + 1

    sorted_confusions = sorted(confusion_counts.items(), key=lambda x: x[1], reverse=True)
    top_confusion_pairs = [{"pair": pair, "count": count} for pair, count in sorted_confusions[:10]]

    # 3. Weakest condition factor levels across the unit (from Bayesian skill_cells)
    cursor.execute("""
        SELECT factor, level, SUM(alpha) as total_alpha, SUM(beta) as total_beta, SUM(n) as total_n
        FROM skill_cells
        WHERE factor != '' AND level != ''
        GROUP BY factor, level;
    """)
    cond_rows = cursor.fetchall()
    weakest_conditions = []
    for cr in cond_rows:
        tot_a = float(cr["total_alpha"])
        tot_b = float(cr["total_beta"])
        tot_n = int(cr["total_n"])
        mean_prof = tot_a / (tot_a + tot_b) if (tot_a + tot_b) > 0 else 0.5
        weakest_conditions.append(
            {
                "factor": cr["factor"],
                "level": cr["level"],
                "mean_proficiency": round(mean_prof, 3),
                "n_observations": tot_n,
            }
        )
    weakest_conditions.sort(key=lambda x: x["mean_proficiency"])
    weakest_conditions = weakest_conditions[:10]

    # 4. Mean coverage across trainees
    cursor.execute("SELECT id FROM trainees;")
    trainee_ids = [r["id"] for r in cursor.fetchall()]
    conn.close()

    if trainee_ids:
        coverages = [float(coverage_report(tid)) for tid in trainee_ids]
        mean_cov = round(float(np.mean(coverages)), 4)
    else:
        mean_cov = 0.0

    return {
        "score_distribution": score_dist,
        "top_confusion_pairs": top_confusion_pairs,
        "weakest_conditions": weakest_conditions,
        "mean_coverage": mean_cov,
    }


@app.get("/decision-tree")
def get_decision_tree_endpoint() -> Dict[str, Any]:
    """Retrieve decision tree SOP rules and validation status (read-only)."""
    return load_decision_tree()


@app.get("/validation")
def get_validation_report() -> Dict[str, Any]:
    """Retrieve ground-truth Bayesian skill recovery validation report."""
    report_file = BASE_DIR / "data" / "validation_report.json"
    if not report_file.exists():
        return {
            "status": "pending",
            "message": "Validation report not generated yet. Run test_recovery.py to produce evidence.",
            "r": None,
            "sessions": 0,
        }
    try:
        # json is imported at top of module
        with open(report_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed reading validation report: {e}")


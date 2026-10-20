"""Unit tests for DroneDrill AI Simulated Telemetry Layer.

Tests:
1. SimulatedSource is deterministic for the same scenario fingerprint.
2. TelemetryAdapter drops invalid packets and counts them.
3. Packet count matches duration x 5 Hz per object.
4. /aar returns all keys for a scored session.
5. Held-out cells are untouched.
6. LogFileSource reads synthetic placeholder log file.
"""

import uuid
import pytest
from fastapi.testclient import TestClient

from app.factors import HELD_OUT_CELLS, PRACTICE_CELLS
from app.generator import generate_scenario, generate_for_cell
from app.main import app
from app.telemetry import (
    Packet,
    SimulatedSource,
    LogFileSource,
    TelemetryAdapter,
)


@pytest.fixture
def client():
    return TestClient(app)


def test_simulated_source_is_deterministic():
    """Requirement: SimulatedSource is deterministic."""
    scenario = generate_scenario(rng=777, allow_held_out=False)

    source = SimulatedSource(sample_rate_hz=5.0)
    stream_1 = source.packets(scenario)
    stream_2 = source.packets(scenario)

    assert len(stream_1) == len(stream_2)
    assert len(stream_1) > 0

    for p1, p2 in zip(stream_1, stream_2):
        assert p1.t == p2.t
        assert p1.object_id == p2.object_id
        assert p1.x_m == p2.x_m
        assert p1.y_m == p2.y_m
        assert p1.alt_m == p2.alt_m
        assert p1.speed_mps == p2.speed_mps
        assert p1.heading_deg == p2.heading_deg
        assert p1.source == p2.source


def test_adapter_drops_invalid_packets_and_counts_them():
    """Requirement: adapter drops invalid packets and counts them."""
    test_packets = [
        # 1. Valid packet
        Packet(t=0.0, object_id="obj_1", x_m=100.0, y_m=200.0, alt_m=50.0, speed_mps=15.0, heading_deg=90.0, source="simulated"),
        # 2. Invalid negative altitude
        Packet(t=0.2, object_id="obj_1", x_m=103.0, y_m=200.0, alt_m=-10.0, speed_mps=15.0, heading_deg=90.0, source="simulated"),
        # 3. Invalid spatial coordinate out of bounds
        Packet(t=0.4, object_id="obj_1", x_m=250000.0, y_m=200.0, alt_m=50.0, speed_mps=15.0, heading_deg=90.0, source="simulated"),
        # 4. Invalid negative speed
        Packet(t=0.6, object_id="obj_1", x_m=106.0, y_m=200.0, alt_m=50.0, speed_mps=-5.0, heading_deg=90.0, source="simulated"),
        # 5. Valid packet
        Packet(t=0.8, object_id="obj_1", x_m=109.0, y_m=200.0, alt_m=50.0, speed_mps=15.0, heading_deg=90.0, source="simulated"),
        # 6. Invalid decreasing timestamp for obj_1 (t=0.5 < 0.8)
        Packet(t=0.5, object_id="obj_1", x_m=112.0, y_m=200.0, alt_m=50.0, speed_mps=15.0, heading_deg=90.0, source="simulated"),
        # 7. Valid packet for another object
        Packet(t=0.0, object_id="obj_2", x_m=500.0, y_m=500.0, alt_m=80.0, speed_mps=20.0, heading_deg=180.0, source="simulated"),
    ]

    result = TelemetryAdapter.process(test_packets)
    stats = result["stats"]
    valid_packets = result["packets"]

    assert stats["total_received"] == 7
    assert stats["dropped_count"] == 4
    assert stats["valid_count"] == 3
    assert len(valid_packets) == 3


def test_packet_count_matches_duration_times_5hz_per_object():
    """Requirement: packet count matches duration x 5 Hz per object."""
    objects = [
        {"id": "target_alpha", "true_class": "multirotor", "start_position": [1000, 1000, 100], "velocity": [-10, -10, 0]},
        {"id": "target_bravo", "true_class": "fixed_wing_uav", "start_position": [2000, 1500, 150], "velocity": [-20, -15, 0]},
        {"id": "target_charlie", "true_class": "bird", "start_position": [800, 800, 50], "velocity": [-8, -8, 0]},
    ]
    duration_s = 60.0
    scenario = {
        "scenario_id": "test_count_scenario",
        "cell": ["day", "clear", "open", "EO", "none", "none"],
        "objects": objects,
        "duration_s": duration_s,
        "difficulty_index": 0.5,
        "fingerprint": "count_check_fp_123",
    }

    source = SimulatedSource(sample_rate_hz=5.0)
    packets = source.packets(scenario)

    expected_per_object = int(duration_s * 5)  # 60 * 5 = 300 packets per object
    expected_total = len(objects) * expected_per_object  # 3 * 300 = 900

    assert len(packets) == expected_total

    # Check each individual object's packet count
    for obj in objects:
        obj_pkts = [p for p in packets if p.object_id == obj["id"]]
        assert len(obj_pkts) == expected_per_object, (
            f"Object {obj['id']} has {len(obj_pkts)} packets, expected {expected_per_object}"
        )


def test_aar_returns_all_keys_for_a_scored_session(client):
    """Requirement: /aar returns all keys for a scored session."""
    trainee_id = f"trainee_aar_eval_{uuid.uuid4().hex[:8]}"

    # 1. Start a session
    start_resp = client.post("/session/start", json={"trainee_id": trainee_id, "mode": "practice"})
    assert start_resp.status_code == 200
    start_data = start_resp.json()
    session_id = start_data["session_id"]
    scenario = start_data["scenario"]

    # 2. Complete session with interaction events
    events = [
        {
            "object_id": obj["id"],
            "detected": True,
            "detect_time_s": 3.5,
            "classified_as": obj["true_class"],
            "threat_level_rated": obj["true_threat_level"],
            "response_chosen": "monitor",
            "confidence": 0.85,
        }
        for obj in scenario.get("objects", [])
    ]

    res_resp = client.post(
        "/session/result",
        json={
            "session_id": session_id,
            "events": events,
            "false_alarms": 1,
        },
    )
    assert res_resp.status_code == 200

    # 3. Request After Action Review (AAR)
    aar_resp = client.get(f"/aar/{session_id}")
    assert aar_resp.status_code == 200
    aar_data = aar_resp.json()

    # Validate all required keys
    required_keys = [
        "session_id",
        "trainee_id",
        "scenario_id",
        "overall_score",
        "ground_truth",
        "sensor_view",
        "visibility_windows",
        "trainee_actions",
        "timeline",
        "errors",
        "confidence_vs_correctness",
        "feedback_sentences",
    ]
    for key in required_keys:
        assert key in aar_data, f"Missing required AAR key: {key}"

    # Check error taxonomy subkeys
    error_subkeys = ["missed", "misclassifications", "wrong_threat_levels", "suboptimal_responses", "false_alarms"]
    for subkey in error_subkeys:
        assert subkey in aar_data["errors"], f"Missing error taxonomy subkey: {subkey}"

    # Also check /scenario/{session_id}/telemetry
    telemetry_resp = client.get(f"/scenario/{session_id}/telemetry")
    assert telemetry_resp.status_code == 200
    telem_data = telemetry_resp.json()
    assert "packets" in telem_data
    assert "visibility_windows" in telem_data
    assert "adapter_stats" in telem_data
    assert "objects" in telem_data
    assert telem_data["source"] == "simulated"


def test_held_out_cells_are_untouched():
    """Requirement: held-out cells are untouched."""
    assert len(HELD_OUT_CELLS) == 360
    assert len(PRACTICE_CELLS) == 1440
    assert len(HELD_OUT_CELLS.intersection(PRACTICE_CELLS)) == 0

    # In practice mode, telemetry generation never draws from HELD_OUT_CELLS
    scenario = generate_scenario(rng=99, allow_held_out=False)
    assert tuple(scenario["cell"]) not in HELD_OUT_CELLS

    source = SimulatedSource()
    packets = source.packets(scenario)
    assert len(packets) > 0


def test_log_file_source_reads_placeholder():
    """Verify LogFileSource loads placeholder telemetry packets."""
    scenario = generate_scenario(rng=12, allow_held_out=False)
    source = LogFileSource()
    packets = source.packets(scenario)

    assert len(packets) == 120
    assert all(p.source == "log_file" for p in packets)
    assert all(p.object_id == scenario["objects"][0]["id"] for p in packets)

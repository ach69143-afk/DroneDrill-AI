"""DroneDrill AI - Synthetic Cohort Demo Seeder.

Populates 10 synthetic trainees (flagged is_demo=1) with realistic practice and test sessions
generated directly via SimLearner without HTTP overhead.

Profiles:
- 3 Strong Generalizers (high latent skill, low rote gap, high test performance)
- 3 Rote Learners (moderate baseline, high rote bonus on repeated fingerprints, lower test)
- 4 Mixed Condition Trainees (distinct condition weaknesses: fog/EO, night/noise, urban/occlusion, clutter/rain)

Deterministic seed and fully idempotent (clears existing demo trainees on re-run).
"""

import sys
from pathlib import Path
import random
import uuid
from typing import Any, Dict, List, Optional

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import (
    init_db,
    record_trainee,
    record_session,
    record_cell_seen,
    record_fingerprint,
    record_event,
    update_session_score,
    clear_demo_trainees,
    get_trainee_sessions,
)
from app.factors import init_split, PRACTICE_CELLS, HELD_OUT_CELLS
from app.generator import generate_scenario, generate_for_cell
from app.sim_learner import SimLearner
from app.skill_model import update_from_result
from app.generalization import generalization_score, rote_indicator
from app.telemetry import SimulatedSource, TelemetryAdapter
from app.recorder import record_telemetry

SEED = 2026


def seed_demo_data(seed: int = SEED, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Seed 10 synthetic demo trainees with complete evaluation histories."""
    init_db(db_path=db_path)
    init_split()

    rng = random.Random(seed)

    # 1. Idempotently clear existing demo trainees
    cleared_count = clear_demo_trainees(db_path=db_path)

    # 2. Define trainee profile configurations
    trainee_profiles = [
        # Strong Generalizers (1 - 3)
        {
            "id": "demo_trainee_01",
            "name": "Demo Trainee 01",
            "type": "Strong Generalizer",
            "base_skill": 0.88,
            "rote_bonus": 0.02,
            "condition_skills": {},
            "n_practice": 10,
            "n_test": 3,
            "n_repeats": 2,
        },
        {
            "id": "demo_trainee_02",
            "name": "Demo Trainee 02",
            "type": "Strong Generalizer",
            "base_skill": 0.86,
            "rote_bonus": 0.03,
            "condition_skills": {},
            "n_practice": 11,
            "n_test": 3,
            "n_repeats": 2,
        },
        {
            "id": "demo_trainee_03",
            "name": "Demo Trainee 03",
            "type": "Strong Generalizer",
            "base_skill": 0.85,
            "rote_bonus": 0.01,
            "condition_skills": {},
            "n_practice": 9,
            "n_test": 3,
            "n_repeats": 2,
        },
        # Rote Learners (4 - 6)
        {
            "id": "demo_trainee_04",
            "name": "Demo Trainee 04",
            "type": "Rote Learner",
            "base_skill": 0.50,
            "rote_bonus": 0.42,
            "condition_skills": {},
            "n_practice": 10,
            "n_test": 3,
            "n_repeats": 4,
        },
        {
            "id": "demo_trainee_05",
            "name": "Demo Trainee 05",
            "type": "Rote Learner",
            "base_skill": 0.48,
            "rote_bonus": 0.45,
            "condition_skills": {},
            "n_practice": 12,
            "n_test": 3,
            "n_repeats": 4,
        },
        {
            "id": "demo_trainee_06",
            "name": "Demo Trainee 06",
            "type": "Rote Learner",
            "base_skill": 0.52,
            "rote_bonus": 0.40,
            "condition_skills": {},
            "n_practice": 9,
            "n_test": 3,
            "n_repeats": 3,
        },
        # Mixed Condition Trainees (7 - 10)
        {
            "id": "demo_trainee_07",
            "name": "Demo Trainee 07",
            "type": "Mixed (Fog/EO Weakness)",
            "base_skill": 0.78,
            "rote_bonus": 0.05,
            "condition_skills": {("weather", "fog"): 0.35, ("sensor_mode", "EO"): 0.40},
            "n_practice": 10,
            "n_test": 3,
            "n_repeats": 2,
        },
        {
            "id": "demo_trainee_08",
            "name": "Demo Trainee 08",
            "type": "Mixed (Night/Noise Weakness)",
            "base_skill": 0.77,
            "rote_bonus": 0.05,
            "condition_skills": {("time_of_day", "night"): 0.30, ("degradation", "noise"): 0.35},
            "n_practice": 11,
            "n_test": 3,
            "n_repeats": 2,
        },
        {
            "id": "demo_trainee_09",
            "name": "Demo Trainee 09",
            "type": "Mixed (Urban/Occlusion Weakness)",
            "base_skill": 0.79,
            "rote_bonus": 0.05,
            "condition_skills": {("terrain", "urban"): 0.32, ("degradation", "occlusion"): 0.30},
            "n_practice": 10,
            "n_test": 3,
            "n_repeats": 2,
        },
        {
            "id": "demo_trainee_10",
            "name": "Demo Trainee 10",
            "type": "Mixed (Clutter/Rain Weakness)",
            "base_skill": 0.76,
            "rote_bonus": 0.05,
            "condition_skills": {("distractors", "clutter"): 0.35, ("weather", "rain"): 0.38},
            "n_practice": 10,
            "n_test": 3,
            "n_repeats": 2,
        },
    ]

    held_out_list = sorted(list(HELD_OUT_CELLS))
    summary_results: List[Dict[str, Any]] = []

    for prof in trainee_profiles:
        tid = prof["id"]
        tname = prof["name"]

        # Register demo trainee
        record_trainee(tid, name=tname, is_demo=1, db_path=db_path)

        sim = SimLearner(
            base_skill=prof["base_skill"],
            condition_skills=prof["condition_skills"],
            rote_bonus=prof["rote_bonus"],
            rng=rng.randint(1000, 999999),
        )

        practice_scenarios: List[Dict[str, Any]] = []
        n_practice = prof["n_practice"]
        n_repeats = prof["n_repeats"]

        # 3. Generate practice sessions
        for i in range(n_practice):
            session_id = str(uuid.uuid4())
            is_repeat = 0

            # Inject designated repeated scenarios
            if i >= (n_practice - n_repeats) and practice_scenarios:
                repeat_scen = practice_scenarios[i % len(practice_scenarios)]
                scenario = repeat_scen
                is_repeat = 1
            else:
                scenario = generate_scenario(rng=rng.randint(100, 999999), allow_held_out=False)
                practice_scenarios.append(scenario)

            fp = scenario["fingerprint"]

            record_session(
                session_id=session_id,
                trainee_id=tid,
                scenario_id=scenario["scenario_id"],
                cell=scenario["cell"],
                difficulty_index=scenario["difficulty_index"],
                scenario_json=scenario,
                mode="practice",
                is_repeat=is_repeat,
                fingerprint=fp,
                db_path=db_path,
            )
            record_cell_seen(tid, scenario["cell"], db_path=db_path)
            record_fingerprint(fp, scenario["scenario_id"], db_path=db_path)

            # Evaluate with SimLearner directly
            scores = sim.evaluate_scenario(scenario, is_repeat=bool(is_repeat))

            # Store interaction events with sim-time
            for ev in sim.last_events:
                record_event(
                    session_id=session_id,
                    event_type="object_assessment",
                    payload=ev,
                    t_s=float(ev.get("detect_time_s", 0.0)),
                    db_path=db_path,
                )

            if sim.last_false_alarms > 0:
                record_event(
                    session_id=session_id,
                    event_type="false_alarm_count",
                    payload={"count": sim.last_false_alarms},
                    t_s=float(scenario.get("duration_s", 60.0)),
                    db_path=db_path,
                )

            # Store simulated telemetry
            raw_pkts = SimulatedSource().packets(scenario)
            processed_telem = TelemetryAdapter.process(raw_pkts)
            record_telemetry(session_id, processed_telem["packets"], db_path=db_path)

            # Update score and skill model
            update_session_score(session_id, scores["overall_score"], scores, db_path=db_path)
            if "skill_scores" in scores:
                update_from_result(tid, scores["skill_scores"], db_path=db_path)

        # 4. Generate test sessions (held-out cells)
        for _ in range(prof["n_test"]):
            session_id = str(uuid.uuid4())
            test_cell = rng.choice(held_out_list)
            scenario = generate_for_cell(test_cell, rng=rng.randint(100, 999999))
            fp = scenario["fingerprint"]

            record_session(
                session_id=session_id,
                trainee_id=tid,
                scenario_id=scenario["scenario_id"],
                cell=scenario["cell"],
                difficulty_index=scenario["difficulty_index"],
                scenario_json=scenario,
                mode="test",
                is_repeat=0,
                fingerprint=fp,
                db_path=db_path,
            )
            record_fingerprint(fp, scenario["scenario_id"], db_path=db_path)

            scores = sim.evaluate_scenario(scenario, is_repeat=False)

            for ev in sim.last_events:
                record_event(
                    session_id=session_id,
                    event_type="object_assessment",
                    payload=ev,
                    t_s=float(ev.get("detect_time_s", 0.0)),
                    db_path=db_path,
                )

            if sim.last_false_alarms > 0:
                record_event(
                    session_id=session_id,
                    event_type="false_alarm_count",
                    payload={"count": sim.last_false_alarms},
                    t_s=float(scenario.get("duration_s", 60.0)),
                    db_path=db_path,
                )

            raw_pkts = SimulatedSource().packets(scenario)
            processed_telem = TelemetryAdapter.process(raw_pkts)
            record_telemetry(session_id, processed_telem["packets"], db_path=db_path)

            update_session_score(session_id, scores["overall_score"], scores, db_path=db_path)

        # 5. Collect summary metrics for display
        sessions = get_trainee_sessions(tid, db_path=db_path)
        scored = [s for s in sessions if s.get("overall_score") is not None]
        mean_score = sum(s["overall_score"] for s in scored) / len(scored) if scored else 0.0

        gen_eval = generalization_score(tid, db_path=db_path)
        rote_eval = rote_indicator(tid, db_path=db_path)

        summary_results.append(
            {
                "id": tid,
                "name": tname,
                "profile": prof["type"],
                "practice_sessions": prof["n_practice"],
                "test_sessions": prof["n_test"],
                "mean_overall": round(mean_score, 3),
                "generalization_score": gen_eval.get("score"),
                "rote_gap": rote_eval.get("gap"),
            }
        )

    return summary_results


def print_summary_table(results: List[Dict[str, Any]]) -> None:
    """Print clean ASCII summary table to stdout."""
    header = (
        f"{'ID':<18} | {'Name':<16} | {'Profile':<30} | "
        f"{'Prac':>5} | {'Test':>5} | {'Mean Score':>10} | {'Gen Score':>10} | {'Rote Gap':>10}"
    )
    separator = "-" * len(header)

    print("\n" + separator)
    print("DroneDrill AI - Synthetic Trainee Cohort Seeding Summary")
    print(separator)
    print(header)
    print(separator)

    for r in results:
        gen_str = f"{r['generalization_score']:.3f}" if r["generalization_score"] is not None else "N/A"
        rote_str = f"{r['rote_gap']:.3f}" if r["rote_gap"] is not None else "N/A"
        print(
            f"{r['id']:<18} | {r['name']:<16} | {r['profile']:<30} | "
            f"{r['practice_sessions']:>5} | {r['test_sessions']:>5} | "
            f"{r['mean_overall']:>10.3f} | {gen_str:>10} | {rote_str:>10}"
        )
    print(separator + "\n")


if __name__ == "__main__":
    results = seed_demo_data()
    print_summary_table(results)

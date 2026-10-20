"""DroneDrill AI - Phase 1 Scenario Audit Script.

Audits a dusk, haze scenario with 12 objects.
Prints every object:
- id, class, appear_time, disappear_time
- telemetry x_m, y_m, alt_m
- projected screen position
- whether inside sky safe rectangle (x 10-90%, y 8% to horizon-4%)
- occlusion/dropout flags
- whether drawn in main view, in EO, in Thermal, and on radar at each second
"""

import sys
from pathlib import Path
import json
import math

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.factors import get_horizon_fraction
from app.generator import _build_scenario_for_cell, _coerce_rng
from app.sensor_view import compute_object_position_at_t, project_telemetry_safe_sky, visibility_windows


def audit_failing_scenario():
    # Dusk, Haze cell with 12 objects
    cell = ("dusk", "haze", "urban", "EO", "dropout", "none")
    rng = _coerce_rng(42)
    scenario = _build_scenario_for_cell(cell, rng=rng, object_count="9+")
    
    # Ensure exactly 12 objects
    if len(scenario["objects"]) < 12:
        # Pad to 12 if needed
        while len(scenario["objects"]) < 12:
            base_obj = dict(scenario["objects"][0])
            idx = len(scenario["objects"]) + 1
            base_obj["id"] = f"obj_{idx}"
            scenario["objects"].append(base_obj)

    print("=" * 100)
    print("PHASE 1 AUDIT: SCENARIO DETAILS")
    print(f"Scenario ID: {scenario['scenario_id']}")
    print(f"Factors: {scenario['factors']}")
    print(f"Duration: {scenario['duration_s']}s")
    print(f"Objects Count: {len(scenario['objects'])}")
    print("=" * 100)

    W = 1920.0
    H = 1080.0
    horizon_frac = get_horizon_fraction(scenario["factors"]["terrain"], scenario["factors"]["time_of_day"])
    min_x = W * 0.10
    max_x = W * 0.90
    min_y = H * 0.08
    max_y = H * (horizon_frac - 0.04)

    print(f"\nSafe Sky Rectangle (W={W}, H={H}, Horizon={horizon_frac}):")
    print(f"  X Safe: [{min_x:.1f}, {max_x:.1f}]")
    print(f"  Y Safe: [{min_y:.1f}, {max_y:.1f}]")

    vis_map = visibility_windows(scenario)

    for obj in scenario["objects"]:
        oid = obj["id"]
        true_cls = obj.get("true_class", "unknown")
        app_t = float(obj.get("appears_at_time", 0.0))
        motion = obj.get("motion_pattern", scenario["factors"].get("motion_pattern", "straight"))
        dur_s = float(scenario.get("duration_s", 60.0))

        # Check visibility windows
        wins = vis_map.get(oid, [])
        visible_intervals = [(w["from_t"], w["to_t"]) for w in wins if w.get("visible", False)]
        disappear_t = visible_intervals[-1][1] if visible_intervals else app_t

        print("-" * 100)
        print(f"OBJECT: {oid} | Class: {true_cls} | Appears: {app_t:.1f}s | Disappears: {disappear_t:.1f}s | Motion: {motion}")
        print(f"Start Pos: {obj.get('start_position')} | Velocity: {obj.get('velocity')}")
        print(f"Visibility Windows: {wins}")

        # Sample second-by-second (first 10 seconds and key timestamps)
        sample_times = [round(t, 1) for t in range(int(min(dur_s, 15)) + 1)]
        print("\n  Second-by-second breakdown:")
        print("  Sec | Telemetry (x, y, alt)       | Screen (X, Y)  | In Sky Box? | Dropout/Occ? | Main | EO  | Therm | Radar")
        for t in sample_times:
            if t < app_t:
                x, y, z = compute_object_position_at_t(obj, app_t, dur_s, motion)
                proj = project_telemetry_safe_sky(x, y, z, scenario['factors']['terrain'], scenario['factors']['time_of_day'], W, H)
                print(f"  {t:3.0f} | ({x:6.1f}, {y:6.1f}, {z:5.1f}) | ({proj['scrX']:6.1f}, {proj['scrY']:6.1f}) | {str(proj['is_inside']):11} | NOT_ENTERED  | NO   | NO  | NO    | YES (bug!)")
                continue

            x, y, z = compute_object_position_at_t(obj, t, dur_s, motion)
            proj = project_telemetry_safe_sky(x, y, z, scenario['factors']['terrain'], scenario['factors']['time_of_day'], W, H)
            
            # Check degradation
            is_masked = False
            mask_reason = "none"
            for w in wins:
                if w["from_t"] <= t <= w["to_t"]:
                    if not w.get("visible", True):
                        is_masked = True
                        mask_reason = w.get("reason", "masked")
                    break

            in_box = proj["is_inside"]
            main_vis = in_box and not is_masked
            eo_vis = in_box and not is_masked
            thermal_vis = in_box and not is_masked
            radar_vis = True  # CURRENT CLIENT BUG: radar draws all active objects!

            print(f"  {t:3.0f} | ({x:6.1f}, {y:6.1f}, {z:5.1f}) | ({proj['scrX']:6.1f}, {proj['scrY']:6.1f}) | {str(in_box):11} | {mask_reason[:12]:12} | {'YES' if main_vis else 'NO':4} | {'YES' if eo_vis else 'NO':3} | {'YES' if thermal_vis else 'NO':5} | {'YES' if radar_vis else 'NO'}")

    print("=" * 100)


if __name__ == "__main__":
    audit_failing_scenario()

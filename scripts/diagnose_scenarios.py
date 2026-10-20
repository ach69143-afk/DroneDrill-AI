"""DroneDrill AI - Scenario Diagnosis Script.

Diagnoses scenarios for:
1. night + rain + forest
2. night + urban + clear

Prints the scenario details, its visibility_windows, and on-screen coordinates.
"""

import sys
from pathlib import Path
import json

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.factors import init_split, all_cells
from app.generator import generate_for_cell
from app.sensor_view import visibility_windows, check_main_view_visibility


def diagnose_case(title: str, cell: tuple):
    print("=" * 80)
    print(f"DIAGNOSIS: {title}")
    print(f"Condition Cell: {cell}")
    print("=" * 80)

    scenario = generate_for_cell(cell)
    print(f"\nScenario ID: {scenario['scenario_id']}")
    print(f"Duration: {scenario['duration_s']}s")
    print(f"Factors: {json.dumps(scenario['factors'], indent=2)}")
    print(f"Number of Objects: {len(scenario['objects'])}")

    vis_windows = visibility_windows(scenario)
    print("\nVisibility Windows:")
    for oid, windows in vis_windows.items():
        print(f"  Object {oid}:")
        for w in windows:
            print(f"    t={w['from_t']}..{w['to_t']}s | visible={w['visible']} | reason={w.get('reason', '')}")

    print("\nObject Spatial Coordinates and On-Screen Projection (Canvas w=1200, h=800):")
    w_canvas = 1200
    h_canvas = 800
    horizon_y = h_canvas * 0.65

    for obj in scenario["objects"]:
        oid = obj["id"]
        x0, y0, z0 = obj["start_position"]
        vx, vy, vz = obj["velocity"]
        app_t = obj["appears_at_time"]
        print(f"\n  Object {oid} ({obj['true_class']}):")
        print(f"    Appears at: {app_t}s")
        print(f"    Start Position: x={x0}m, y={y0}m, z={z0}m")
        print(f"    Velocity: vx={vx}m/s, vy={vy}m/s, vz={vz}m/s")

        print("    Sampled Timesteps:")
        for t in [app_t, app_t + 5.0, app_t + 10.0, min(scenario["duration_s"] - 1.0, app_t + 20.0)]:
            xt = x0 + vx * t
            yt = y0 + vy * t
            zt = max(10.0, z0 + vz * t)
            dist = (xt**2 + yt**2)**0.5
            if dist > 0 and yt > 0:
                fov_scale = (w_canvas * 0.8) / dist
                scr_x = w_canvas / 2 + xt * fov_scale
                scr_y = horizon_y - (zt * fov_scale * 1.2)
                on_screen = (0 <= scr_x <= w_canvas) and (0 <= scr_y <= h_canvas)
                print(f"      t={t:5.1f}s | pos=({xt:7.1f}, {yt:7.1f}, {zt:5.1f}) | screen=({scr_x:6.1f}, {scr_y:6.1f}) | on_screen={on_screen}")
            else:
                print(f"      t={t:5.1f}s | pos=({xt:7.1f}, {yt:7.1f}, {zt:5.1f}) | BEHIND/CLOSE")

    valid = check_main_view_visibility(scenario, min_consecutive_s=6.0)
    print(f"\n6-Second Main View Validity Check: {'PASSED' if valid else 'FAILED'}")
    print("=" * 80 + "\n")


def main():
    init_split()

    # Case 1: night + rain + forest
    # (time_of_day, weather, terrain, sensor_mode, degradation, distractors)
    case1_cell = ("night", "rain", "forest", "EO", "occlusion", "birds")
    diagnose_case("Case 1: Night + Rain + Forest", case1_cell)

    # Case 2: night + urban + clear
    case2_cell = ("night", "clear", "urban", "EO", "none", "none")
    diagnose_case("Case 2: Night + Urban + Clear", case2_cell)


if __name__ == "__main__":
    main()

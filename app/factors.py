"""DroneDrill AI - Factor Definitions and Cell Splitting.

Condition factors define a simulation 'cell'.
Object-level factors specify targets within the scenario.
Maintains a deterministic 80/20 train/held-out split persisted to data/split.json.
"""

from pathlib import Path
import json
import itertools
import random
from typing import List, Tuple, Set

# Base and data directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SPLIT_FILE = DATA_DIR / "split.json"

# --- Condition Factors (Define a "cell") ---
TIME_OF_DAY = ["day", "dusk", "night"]
WEATHER = ["clear", "haze", "fog", "rain", "dust"]
TERRAIN = ["open", "urban", "forest", "hills"]
SENSOR_MODE = ["EO", "thermal"]
DEGRADATION = ["none", "noise", "lag", "dropout", "occlusion"]
DISTRACTORS = ["none", "birds", "clutter"]

CONDITION_FACTOR_NAMES = [
    "time_of_day",
    "weather",
    "terrain",
    "sensor_mode",
    "degradation",
    "distractors",
]

# --- Object-Level Factors ---
OBJECT_COUNT_LEVELS = ["1", "2-3", "4-8", "9+"]
CLASS_MIX = [
    "bird",
    "balloon",
    "light_aircraft",
    "multirotor",
    "fixed_wing_uav",
    "unknown",
]
MOTION_PATTERN = ["straight", "loiter", "erratic", "parallel", "converging"]
SPEED_BAND = ["low", "med", "high"]
ALTITUDE_BAND = ["low", "med", "high"]
BEARING_SECTOR = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
BEHAVIOUR_LABEL = ["benign", "suspicious"]

# --- Canvas Projection Reference Horizon Fractions ---
HORIZON_FRACTIONS = {
    "open_day": 0.60,
    "open_night": 0.66,
    "urban_day": 0.58,
    "urban_night": 0.64,
    "forest_day": 0.62,
    "forest_night": 0.80,
    "hills_day": 0.74,
    "hills_night": 0.69,
}


def get_horizon_fraction(terrain: str, time_of_day: str) -> float:
    """Return horizon fraction matching client/renderer.js. Dusk uses the day background."""
    base_time = "day" if time_of_day == "dusk" else (time_of_day or "day")
    key = f"{terrain}_{base_time}"
    return HORIZON_FRACTIONS.get(key, 0.65)


def all_cells() -> List[Tuple[str, str, str, str, str, str]]:
    """Return every combination of condition factors as a list of tuples.
    
    Total combinations: 3 * 5 * 4 * 2 * 5 * 3 = 1800 cells.
    """
    return list(
        itertools.product(
            TIME_OF_DAY,
            WEATHER,
            TERRAIN,
            SENSOR_MODE,
            DEGRADATION,
            DISTRACTORS,
        )
    )


def init_split(split_file: Path = SPLIT_FILE, seed: int = 42) -> Tuple[Set[Tuple[str, ...]], Set[Tuple[str, ...]]]:
    """Generate or load the deterministic 80% practice / 20% held-out cell split.
    
    Persists to data/split.json.
    """
    split_file = Path(split_file)
    if split_file.exists():
        try:
            with open(split_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                held_out = set(tuple(c) for c in data.get("held_out", []))
                practice = set(tuple(c) for c in data.get("practice", []))
                if held_out and practice:
                    return held_out, practice
        except Exception:
            # Fall back to regenerating if corrupted
            pass

    # Deterministic generation using fixed seed
    cells = all_cells()
    rng = random.Random(seed)
    shuffled = list(cells)
    rng.shuffle(shuffled)

    # 20% HELD_OUT, 80% PRACTICE
    split_idx = int(len(shuffled) * 0.2)
    held_out_list = shuffled[:split_idx]
    practice_list = shuffled[split_idx:]

    split_file.parent.mkdir(parents=True, exist_ok=True)
    with open(split_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "seed": seed,
                "total_cells": len(cells),
                "held_out_count": len(held_out_list),
                "practice_count": len(practice_list),
                "held_out": held_out_list,
                "practice": practice_list,
            },
            f,
            indent=2,
        )

    return set(held_out_list), set(practice_list)


# Initialize the split on module load
HELD_OUT_CELLS, PRACTICE_CELLS = init_split()

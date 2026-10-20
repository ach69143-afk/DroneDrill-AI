"""DroneDrill AI - Bayesian Skill Model.

Maintains Beta(alpha, beta) posterior distributions per trainee x skill x condition factor level.
Initializes with an uninformative prior Beta(1, 1).
Parses skill-wise outputs from scoring.py and updates factor levels.
"""

from pathlib import Path
import json
import math
from typing import Any, Dict, List, Optional, Tuple

from app.db import get_connection, record_trainee
from app.factors import (
    CONDITION_FACTOR_NAMES,
    TIME_OF_DAY,
    WEATHER,
    TERRAIN,
    SENSOR_MODE,
    DEGRADATION,
    DISTRACTORS,
)

# 5 Core Skills
SKILLS = ["detection", "classification", "decision", "timeliness", "calibration"]

# Factor levels map
FACTOR_LEVELS: Dict[str, List[str]] = {
    "time_of_day": TIME_OF_DAY,
    "weather": WEATHER,
    "terrain": TERRAIN,
    "sensor_mode": SENSOR_MODE,
    "degradation": DEGRADATION,
    "distractors": DISTRACTORS,
}


def parse_skill_key(key: str) -> Optional[Tuple[str, List[str]]]:
    """Parse skill and 6 factor levels from skill_scores key, e.g., 'classification|day/clear/open/EO/none/none'."""
    if "|" not in key:
        return None
    skill, cell_str = key.split("|", 1)
    if skill not in SKILLS:
        return None

    if cell_str.startswith("["):
        try:
            levels = json.loads(cell_str)
        except Exception:
            levels = cell_str.split("/")
    elif "/" in cell_str:
        levels = cell_str.split("/")
    else:
        levels = cell_str.split(",")

    if len(levels) != 6:
        return None
    return skill, [str(lvl).strip() for lvl in levels]


def update_from_result(
    trainee_id: str,
    skill_scores: Dict[str, Any],
    db_path: Optional[str] = None,
) -> None:
    """Update Beta(alpha, beta) parameters for each skill x factor level from scoring outputs.
    
    For each score s in [0, 1]:
        alpha += s
        beta += 1.0 - s
        n += 1
    Persisted in skill_cells table.
    """
    record_trainee(trainee_id, db_path=db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    for key, val in skill_scores.items():
        parsed = parse_skill_key(key)
        if not parsed:
            continue
        skill, levels = parsed

        try:
            score = float(val)
        except (ValueError, TypeError):
            continue
        s = max(0.0, min(1.0, score))

        for factor_name, level_val in zip(CONDITION_FACTOR_NAMES, levels):
            cell_key = f"{skill}:{factor_name}:{level_val}"

            cursor.execute(
                "SELECT alpha, beta, n, seen_count FROM skill_cells WHERE trainee_id = ? AND cell = ?;",
                (trainee_id, cell_key),
            )
            row = cursor.fetchone()

            if row:
                alpha = float(row["alpha"]) + s
                beta = float(row["beta"]) + (1.0 - s)
                n = int(row["n"]) + 1
                seen_count = int(row["seen_count"]) + 1
            else:
                alpha = 1.0 + s
                beta = 1.0 + (1.0 - s)
                n = 1
                seen_count = 1

            cursor.execute(
                """
                INSERT INTO skill_cells (trainee_id, cell, skill, factor, level, alpha, beta, n, seen_count, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(trainee_id, cell) DO UPDATE SET
                    alpha = excluded.alpha,
                    beta = excluded.beta,
                    n = excluded.n,
                    seen_count = excluded.seen_count,
                    last_seen = CURRENT_TIMESTAMP;
                """,
                (trainee_id, cell_key, skill, factor_name, level_val, alpha, beta, n, seen_count),
            )

    conn.commit()
    conn.close()


def get_posterior(
    trainee_id: str,
    skill: str,
    factor: str,
    level: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Calculate Beta posterior statistics {mean, sd, n} for trainee x skill x factor level."""
    cell_key = f"{skill}:{factor}:{level}"
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT alpha, beta, n FROM skill_cells WHERE trainee_id = ? AND cell = ?;",
        (trainee_id, cell_key),
    )
    row = cursor.fetchone()
    conn.close()

    if row is not None:
        alpha = float(row["alpha"])
        beta = float(row["beta"])
        n = int(row["n"])
    else:
        # Default uninformative prior Beta(1, 1)
        alpha = 1.0
        beta = 1.0
        n = 0

    mean = alpha / (alpha + beta)
    denom = ((alpha + beta) ** 2) * (alpha + beta + 1.0)
    var = (alpha * beta) / denom if denom > 0 else 0.0
    sd = math.sqrt(max(0.0, var))

    return {
        "mean": round(mean, 4),
        "sd": round(sd, 4),
        "n": n,
    }


def weak_conditions(
    trainee_id: str,
    skill: Optional[str] = None,
    min_evidence: int = 3,
    threshold: float = 0.6,
    db_path: Optional[str] = None,
) -> List[Tuple[str, str, str]]:
    """Return (skill, factor, level) entries with n >= min_evidence and mean < threshold, weakest first."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    if skill:
        cursor.execute(
            "SELECT skill, factor, level, alpha, beta, n FROM skill_cells WHERE trainee_id = ? AND skill = ? AND n >= ?;",
            (trainee_id, skill, min_evidence),
        )
    else:
        cursor.execute(
            "SELECT skill, factor, level, alpha, beta, n FROM skill_cells WHERE trainee_id = ? AND skill != '' AND n >= ?;",
            (trainee_id, min_evidence),
        )
    rows = cursor.fetchall()
    conn.close()

    weak = []
    for row in rows:
        alpha = float(row["alpha"])
        beta = float(row["beta"])
        n = int(row["n"])
        mean = alpha / (alpha + beta)
        if mean < threshold:
            weak.append({
                "entry": (row["skill"], row["factor"], row["level"]),
                "mean": mean,
                "n": n,
            })

    # Sort weakest first (lowest mean first)
    weak.sort(key=lambda x: (x["mean"], -x["n"]))
    return [w["entry"] for w in weak]


def skill_matrix(
    trainee_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Dict[str, Dict[str, Dict[str, Any]]]]:
    """Generate complete skill matrix: {skill: {factor: {level: {mean, sd, n}}}}."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT skill, factor, level, alpha, beta, n FROM skill_cells WHERE trainee_id = ? AND skill != '';",
        (trainee_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    obs_map = {}
    for r in rows:
        key = (r["skill"], r["factor"], r["level"])
        obs_map[key] = (float(r["alpha"]), float(r["beta"]), int(r["n"]))

    prior_mean = 0.5
    prior_sd = round(math.sqrt(1.0 / 12.0), 4)

    matrix: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {}
    for sk in SKILLS:
        matrix[sk] = {}
        for factor_name in CONDITION_FACTOR_NAMES:
            matrix[sk][factor_name] = {}
            for level in FACTOR_LEVELS[factor_name]:
                if (sk, factor_name, level) in obs_map:
                    alpha, beta, n = obs_map[(sk, factor_name, level)]
                    mean = alpha / (alpha + beta)
                    var = (alpha * beta) / (((alpha + beta) ** 2) * (alpha + beta + 1.0))
                    sd = math.sqrt(max(0.0, var))
                    matrix[sk][factor_name][level] = {
                        "mean": round(mean, 4),
                        "sd": round(sd, 4),
                        "n": n,
                    }
                else:
                    matrix[sk][factor_name][level] = {
                        "mean": prior_mean,
                        "sd": prior_sd,
                        "n": 0,
                    }
    return matrix

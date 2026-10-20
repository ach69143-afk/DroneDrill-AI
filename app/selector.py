"""DroneDrill AI - Adaptive Scenario Selector.

Selects the next practice scenario adaptively using Bayesian skill estimates.
Rules and Bayesian updating only, strictly avoiding machine learning.
Guarantees never selecting a HELD_OUT condition cell.
"""

import random
from typing import Any, Dict, Optional, Union
import numpy as np

from app.db import count_practice_sessions
from app.factors import (
    CONDITION_FACTOR_NAMES,
    HELD_OUT_CELLS,
    PRACTICE_CELLS,
)
from app.generator import (
    generate_scenario,
    generate_for_cell,
    _coerce_rng,
)
from app.skill_model import (
    weak_conditions,
    get_posterior,
)


def select_next(
    trainee_id: str,
    rng: Optional[Union[int, random.Random, np.random.Generator]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Adaptively select the next scenario for a trainee based on their skill profile.
    
    Returns:
        {"scenario": scenario_dict, "reason": explanation_string}
    """
    rng_inst = _coerce_rng(rng)

    # Check practice session count and weak conditions with sufficient evidence
    practice_sessions = count_practice_sessions(trainee_id, db_path=db_path)
    weak_list = weak_conditions(trainee_id, min_evidence=3, threshold=0.6, db_path=db_path)

    if practice_sessions < 3 or not weak_list:
        # Sample broadly across practice cells
        scenario = generate_scenario(rng=rng_inst, allow_held_out=False)
        reason = "Not enough evidence yet, sampling broadly"
    else:
        # Weakest identified condition (skill, factor, level)
        w_skill, w_factor, w_level = weak_list[0]
        post = get_posterior(trainee_id, w_skill, w_factor, w_level, db_path=db_path)
        cond_mean = post["mean"]
        cond_n = post["n"]

        factor_idx = CONDITION_FACTOR_NAMES.index(w_factor)
        matching_cells = [c for c in PRACTICE_CELLS if c[factor_idx] == w_level]

        roll = rng_inst.random()
        if roll < 0.7:
            # 70% probability: target the weakest condition
            target_diff = float(np.clip(cond_mean + 0.15, 0.2, 0.9))

            # Generate up to 20 candidate scenarios to match targeted difficulty
            candidates = []
            for _ in range(20):
                c = rng_inst.choice(matching_cells)
                cand = generate_for_cell(c, rng=rng_inst)
                candidates.append(cand)

            best_cand = min(candidates, key=lambda sc: abs(sc["difficulty_index"] - target_diff))
            scenario = best_cand
            reason = (
                f"Targeting {w_skill} in {w_level} "
                f"(mean {cond_mean:.2f} over {cond_n} updates) "
                f"at difficulty {scenario['difficulty_index']:.2f}"
            )
        else:
            # 30% probability: interleave a random PRACTICE cell that does not contain the weak level
            non_weak_cells = [c for c in PRACTICE_CELLS if c[factor_idx] != w_level]
            chosen_cell = rng_inst.choice(non_weak_cells)
            scenario = generate_for_cell(chosen_cell, rng=rng_inst)
            reason = "Interleaving practice across other conditions to reinforce generalized skills"

    # Strict invariant: never select a held-out cell
    cell_tuple = tuple(scenario["cell"])
    assert cell_tuple not in HELD_OUT_CELLS, "Security violation: HELD_OUT cell selected in practice"
    assert cell_tuple in PRACTICE_CELLS, "Integrity violation: Non-practice cell selected"

    return {
        "scenario": scenario,
        "reason": reason,
    }
